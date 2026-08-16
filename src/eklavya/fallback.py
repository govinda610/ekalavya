"""Cross-provider load-balancing + automatic fallback for the chat model.

Every provider here speaks the same Anthropic-compatible API, so the *same*
messages can be replayed against a different provider when one is down or
rate-limited. This module wraps the per-provider ``ChatAnthropic`` in a single
LangChain chat model that, on a transient/provider error, transparently retries
the identical request on the next configured provider — and only surfaces an
error if *all* of them fail.

The wrapper is a real ``BaseChatModel`` so it drops into ``build_agent`` /
deepagents unchanged: ``bind_tools`` / ``bind`` are recorded and replayed on each
provider, and ``invoke`` / ``stream`` / ``ainvoke`` / ``astream`` all funnel through
``_generate`` / ``_stream`` / ``_agenerate`` / ``_astream`` which do the hop.

The SDK already retries within a single provider (network blips, one-off 429s);
the value we add is the CROSS-provider hop, so we keep this layer thin.
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from . import config
from .providers import configured_providers, get_provider


# --- which providers to try, and in what order -----------------------------


def fallback_order(provider_key: str | None = None) -> list[str]:
    """The ordered list of CONFIGURED provider keys to try.

    The requested provider (or, when None, the default if configured, else any
    configured one) goes first; every *other* configured provider follows, so a
    multi-key setup always has a fallback chain. A single-key setup returns a
    chain of length 1 — behaviour is then identical to no fallback at all.
    """
    configured = [p.key for p in configured_providers()]
    if not configured:
        # Nothing configured: honour the explicit/default key so the eventual
        # build_chat_model raises the usual clear "not configured" error.
        return [provider_key or config.DEFAULT_PROVIDER]

    if provider_key and provider_key in configured:
        first = provider_key
    elif config.DEFAULT_PROVIDER in configured:
        first = config.DEFAULT_PROVIDER
    else:
        first = configured[0]

    return [first] + [k for k in configured if k != first]


# --- sticky, cache-friendly balancer ---------------------------------------
#
# Round-robin (the old EKLAVYA_BALANCE=1) spread each new session across providers, which
# THRASHED provider-side prompt caches — every session hit a cold cache. The sticky balancer
# instead keeps ALL requests on ONE provider (the highest-priority configured+eligible one)
# so its cache stays warm, and only moves off it when that provider is actually exhausted
# (a transient/rate-limit/quota/5xx error), cooling it down for a while before it's eligible
# again. When a cooldown expires the provider becomes eligible; we only RECOMPUTE the sticky
# pointer when the current sticky becomes ineligible (so we don't flap back on the instant a
# higher-priority provider recovers mid-session).
#
# State is process-level: a single uvicorn worker owns it. NOTE: a multi-worker deployment
# would need this cooldown map + sticky pointer moved to shared state (Redis/db); today we
# run one worker, so a plain module dict is correct and testable.

# provider_key -> unix timestamp until which it is cooling down (ineligible).
_cooldowns: dict[str, float] = {}
# the provider currently pinned as sticky (or None before the first pick).
_sticky: str | None = None


def _now() -> float:
    return time.time()


def priority_order(provider_key: str | None = None) -> list[str]:
    """Configured providers sorted by the explicit priority order (config.PROVIDER_ORDER),
    with any provider not named in that order appended (stable) after the ranked ones.

    A preferred ``provider_key`` (an explicit Settings choice) is bumped to the very front so
    it becomes the sticky primary, with the priority order as its failover tail.
    """
    configured = [p.key for p in configured_providers()]
    if not configured:
        return [provider_key or config.DEFAULT_PROVIDER]

    rank = {k: i for i, k in enumerate(config.PROVIDER_ORDER)}
    ordered = sorted(configured, key=lambda k: (rank.get(k, len(rank)), k))

    if provider_key and provider_key in configured:
        ordered = [provider_key] + [k for k in ordered if k != provider_key]
    return ordered


def _eligible(order: list[str], now: float) -> list[str]:
    """Providers from ``order`` whose cooldown (if any) has expired at ``now``."""
    return [k for k in order if _cooldowns.get(k, 0.0) <= now]


def sticky_chain(provider_key: str | None = None, now: float | None = None) -> list[str]:
    """The chain for the sticky balancer: the sticky provider first, then the rest of the
    priority order as the per-request failover set.

    AUTO (``provider_key`` None): a shared process-level sticky pointer keeps every session on
    ONE provider so its cache stays warm; it only moves when the current sticky is ineligible
    (in cooldown or no longer configured), never flapping back the instant a higher-priority
    provider recovers mid-session.

    PINNED (``provider_key`` set): that provider leads whenever it's eligible; when it is
    cooling down we lead with the next eligible provider from the priority order. A pinned
    build does NOT touch the shared auto pointer.

    If every provider is cooling down we still return a full chain (lead = highest-priority) so
    a request can try anyway — a cooldown gates *becoming sticky*, never the last-resort
    failover.
    """
    global _sticky
    if now is None:
        now = _now()

    order = priority_order(provider_key)
    if len(order) <= 1:
        if provider_key is None:
            _sticky = order[0] if order else None
        return order

    eligible = _eligible(order, now)
    pool = eligible or order  # all cooling down → best-effort over the full order

    if provider_key is not None:
        # pinned: preferred leads when eligible, else the next eligible provider.
        lead = order[0] if order[0] in pool else pool[0]
        return [lead] + [k for k in order if k != lead]

    # auto: recompute the shared sticky only when the current one is ineligible/unknown.
    if _sticky is None or _sticky not in pool:
        _sticky = pool[0]
    return [_sticky] + [k for k in order if k != _sticky]


def mark_cooldown(provider_key: str, now: float | None = None) -> None:
    """Cool a provider down for config.PROVIDER_COOLDOWN seconds (it exhausted). If it was
    the sticky provider, drop the pointer so the next chain build advances to the next
    eligible provider."""
    global _sticky
    if now is None:
        now = _now()
    _cooldowns[provider_key] = now + config.PROVIDER_COOLDOWN
    if _sticky == provider_key:
        _sticky = None


def _reset_balancer_state() -> None:
    """Clear the process-level sticky/cooldown state (tests only)."""
    global _sticky
    _cooldowns.clear()
    _sticky = None


# --- error classification --------------------------------------------------

# HTTP statuses worth hopping to another provider for: rate-limit (429),
# request-timeout (408), and the 5xx server-side family.
_TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


def is_transient(exc: BaseException) -> bool:
    """True if ``exc`` looks like a provider being down/rate-limited/unauthorised
    for THIS key — i.e. worth retrying the same request on the next provider.

    We classify by the Anthropic SDK exception types when available (they carry a
    ``status_code``), and fall back to duck-typing (``status_code``) plus a small
    keyword sniff so injected/fake errors in tests and non-SDK network errors also
    hop. Programming errors (e.g. ``TypeError``) are NOT transient and propagate.
    """
    try:  # SDK is an optional-extra dep; don't hard-require it here.
        import anthropic

        if isinstance(
            exc,
            (
                anthropic.APIConnectionError,
                anthropic.APITimeoutError,
                anthropic.RateLimitError,
                anthropic.InternalServerError,
                anthropic.AuthenticationError,
                anthropic.PermissionDeniedError,
            ),
        ):
            return True
        if isinstance(exc, anthropic.APIStatusError):
            return exc.status_code in _TRANSIENT_STATUS
    except Exception:
        pass

    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int) and status in _TRANSIENT_STATUS:
        return True

    # Network-layer errors from the underlying http stack.
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True

    text = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "rate limit", "rate_limit", "429", "quota", "overloaded", "timeout",
        "timed out", "connection", "temporarily unavailable", "service unavailable",
        "502", "503", "504", "500", "unauthorized", "authentication", "forbidden",
    )
    return any(m in text for m in markers)


class AllProvidersFailed(RuntimeError):
    """Raised when every configured provider failed for one request."""

    def __init__(self, errors: list[tuple[str, BaseException]]):
        self.errors = errors
        detail = "; ".join(f"{key}: {type(e).__name__}: {e}" for key, e in errors)
        super().__init__(
            f"All {len(errors)} provider(s) failed for this request — {detail}"
        )


# --- the resilient chat model ----------------------------------------------


class FallbackChatModel(BaseChatModel):
    """A ``BaseChatModel`` that tries each provider in ``chain`` until one works.

    It builds a plain per-provider ``ChatAnthropic`` lazily (and caches it), then
    replays any recorded ``bind_tools`` / ``bind`` calls so tools/settings apply to
    whichever provider actually serves the request. On a transient error it hops
    to the next provider with the *same* messages; a non-transient error (a real
    bug in the request) is raised immediately.
    """

    chain: list[str]
    model: str | None = None
    build_kwargs: dict[str, Any] = {}
    # Recorded (method, args, kwargs) to replay on each provider's ChatAnthropic.
    binds: list[tuple[str, tuple, dict]] = []
    # Sticky-auto mode: recompute the chain per request from the live sticky/cooldown state,
    # and cool a provider down when IT (the sticky lead) exhausts — so the next request
    # advances to the next eligible provider. When off, `chain` is used verbatim.
    sticky: bool = False
    preferred: str | None = None

    # pydantic v2 (langchain) config: allow the mutable defaults above.
    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self) -> str:
        return "eklavya-fallback"

    # -- provider construction --

    def _provider_runnable(self, key: str):
        """A ready-to-invoke Runnable for one provider (ChatAnthropic + replayed binds)."""
        from .providers import build_chat_model

        base = build_chat_model(key, model=self.model, **self.build_kwargs)
        runnable = base
        for name, args, kwargs in self.binds:
            runnable = getattr(runnable, name)(*args, **kwargs)
        return runnable

    def _order(self) -> list[str]:
        """The provider chain for THIS request.

        Sticky-auto recomputes it live so a provider that cooled down (exhausted on an earlier
        request) is skipped as the lead and the next eligible provider becomes sticky/warm. A
        pinned (non-sticky) chain is used verbatim.
        """
        if self.sticky:
            return sticky_chain(self.preferred)
        return self.chain

    def _note_failure(self, key: str, order: list[str]) -> None:
        """In sticky mode, cool the lead (sticky) provider down when it exhausts, so the next
        request advances off it. Only the current lead triggers a cooldown — a failover
        provider failing on one request shouldn't evict a still-warm lead."""
        if self.sticky and order and key == order[0]:
            mark_cooldown(key)

    # -- bind_tools / bind: record, don't lose fallback --

    def _with_bind(self, name: str, args: tuple, kwargs: dict) -> "FallbackChatModel":
        clone = FallbackChatModel(
            chain=list(self.chain),
            model=self.model,
            build_kwargs=dict(self.build_kwargs),
            binds=[*self.binds, (name, args, kwargs)],
            sticky=self.sticky,
            preferred=self.preferred,
        )
        return clone

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self._with_bind("bind_tools", (list(tools),), kwargs)

    def bind(self, **kwargs):  # type: ignore[override]
        return self._with_bind("bind", (), kwargs)

    # -- the actual fallback loop, shared by every entry point --

    def _run(self, method: str, *args, **kwargs):
        errors: list[tuple[str, BaseException]] = []
        order = self._order()
        for key in order:
            try:
                runnable = self._provider_runnable(key)
                return getattr(runnable, method)(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                if not is_transient(exc):
                    raise
                self._note_failure(key, order)
                errors.append((key, exc))
        raise AllProvidersFailed(errors)

    async def _arun(self, method: str, *args, **kwargs):
        errors: list[tuple[str, BaseException]] = []
        order = self._order()
        for key in order:
            try:
                runnable = self._provider_runnable(key)
                return await getattr(runnable, method)(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                if not is_transient(exc):
                    raise
                self._note_failure(key, order)
                errors.append((key, exc))
        raise AllProvidersFailed(errors)

    def _run_stream(self, method: str, *args, **kwargs):
        """Streaming needs care: only hop if the FIRST chunk fails. Once a provider
        has started emitting, a mid-stream error can't be replayed cleanly, so we
        let it propagate rather than double-emit from another provider."""
        errors: list[tuple[str, BaseException]] = []
        order = self._order()
        for key in order:
            try:
                runnable = self._provider_runnable(key)
                it = iter(getattr(runnable, method)(*args, **kwargs))
                first = next(it)
            except StopIteration:
                return  # empty stream, provider succeeded with no chunks
            except Exception as exc:  # noqa: BLE001
                if not is_transient(exc):
                    raise
                self._note_failure(key, order)
                errors.append((key, exc))
                continue

            def _drain(first=first, it=it):
                yield first
                yield from it

            return _drain()
        raise AllProvidersFailed(errors)

    async def _arun_stream(self, method: str, *args, **kwargs):
        errors: list[tuple[str, BaseException]] = []
        order = self._order()
        for key in order:
            try:
                runnable = self._provider_runnable(key)
                agen = getattr(runnable, method)(*args, **kwargs).__aiter__()
                first = await agen.__anext__()
            except StopAsyncIteration:
                async def _empty():
                    return
                    yield  # pragma: no cover
                return _empty()
            except Exception as exc:  # noqa: BLE001
                if not is_transient(exc):
                    raise
                self._note_failure(key, order)
                errors.append((key, exc))
                continue

            async def _drain(first=first, agen=agen):
                yield first
                async for chunk in agen:
                    yield chunk

            return _drain()
        raise AllProvidersFailed(errors)

    # -- LangChain Runnable surface: delegate to a provider with fallback --

    def invoke(self, input, config=None, **kwargs):  # type: ignore[override]
        return self._run("invoke", input, config, **kwargs)

    async def ainvoke(self, input, config=None, **kwargs):  # type: ignore[override]
        return await self._arun("ainvoke", input, config, **kwargs)

    def stream(self, input, config=None, **kwargs):  # type: ignore[override]
        result = self._run_stream("stream", input, config, **kwargs)
        return iter(()) if result is None else result

    async def astream(self, input, config=None, **kwargs):  # type: ignore[override]
        result = await self._arun_stream("astream", input, config, **kwargs)
        if result is None:
            async def _empty():
                return
                yield  # pragma: no cover
            return _empty()
        return result

    # BaseChatModel demands these; they're only hit if something calls the model
    # via the low-level generate path rather than invoke/stream. Route them
    # through the same fallback so behaviour is consistent.
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._run("_generate", messages, stop, run_manager, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return await self._arun("_agenerate", messages, stop, run_manager, **kwargs)


def build_fallback_chat_model(
    provider_key: str | None = None,
    model: str | None = None,
    balance: bool | None = None,  # retained for call-site compat; no longer round-robin
    **kwargs,
) -> FallbackChatModel:
    """Build the resilient chat model.

    Sticky-auto is the DEFAULT: with no explicit ``provider_key`` the model keeps every
    request on ONE provider (the highest-priority configured+eligible one, per
    config.PROVIDER_ORDER) so its prompt cache stays warm, advancing only when that provider
    exhausts (cooling it down). The full priority order remains the per-request failover set.

    - ``provider_key`` set → that provider is PINNED as the sticky primary (still with the
      priority order behind it as failover). This is an explicit Settings choice.
    - ``provider_key`` None → sticky-auto over the configured providers.
    - Single configured provider → chain of length 1, identical to no fallback.

    ``balance`` is accepted but ignored — the old round-robin entry balancer is retired; the
    sticky balancer supersedes it (see EKLAVYA_BALANCE deprecation in config.py).
    """
    if provider_key is None:
        # sticky-auto: chain recomputed live from the sticky/cooldown state each request.
        order = priority_order(None)
        return FallbackChatModel(
            chain=order, model=model, build_kwargs=kwargs, sticky=True, preferred=None
        )
    # explicit pin: this provider leads and is sticky, with the priority order as failover.
    order = priority_order(provider_key)
    return FallbackChatModel(
        chain=order, model=model, build_kwargs=kwargs, sticky=True, preferred=provider_key
    )
