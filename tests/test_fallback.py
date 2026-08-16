"""Cross-provider fallback + load-balancing — all offline, no network, no real keys.

Provider failures are simulated by injecting fake models that raise; we assert the
wrapper hops to the next provider, returns on the first success, and raises a clear
aggregate error only when every provider fails.
"""

import os
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="eklavya-fallback-")
os.environ["EKLAVYA_HOME"] = _TMP

# Provider env vars that might leak in from the real shell — clear them so tests
# control exactly which providers are "configured".
_ALL_KEYS = [
    "EKLAVYA_GLM_API_KEY", "GLM_API_KEY", "Z_AI_API_KEY",
    "EKLAVYA_MINIMAX_API_KEY", "MINIMAX_API_KEY",
    "EKLAVYA_QWEN_API_KEY", "QWEN_API_KEY", "DASHSCOPE_API_KEY",
    "EKLAVYA_KIMI_API_KEY", "KIMI_API_KEY", "MOONSHOT_API_KEY",
]

from eklavya import config, fallback  # noqa: E402
from eklavya.fallback import (  # noqa: E402
    AllProvidersFailed,
    FallbackChatModel,
    build_fallback_chat_model,
    fallback_order,
    is_transient,
    priority_order,
    sticky_chain,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _ALL_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EKLAVYA_PROVIDER", "glm")
    monkeypatch.setattr(config, "DEFAULT_PROVIDER", "glm")  # legacy fallback_order default
    monkeypatch.delenv("EKLAVYA_BALANCE", raising=False)
    # deterministic priority order + cooldown, and a clean sticky/cooldown state per test.
    monkeypatch.setattr(config, "PROVIDER_ORDER", ["qwen", "kimi", "glm", "minimax"])
    monkeypatch.setattr(config, "PROVIDER_COOLDOWN", 300)
    fallback._reset_balancer_state()
    yield
    fallback._reset_balancer_state()


def _configure(monkeypatch, *keys):
    """Mark the given provider keys as configured via their env token."""
    env = {"glm": "EKLAVYA_GLM_API_KEY", "minimax": "EKLAVYA_MINIMAX_API_KEY",
           "qwen": "EKLAVYA_QWEN_API_KEY", "kimi": "EKLAVYA_KIMI_API_KEY"}
    for key in keys:
        monkeypatch.setenv(env[key], f"test-{key}-token")


class _OKModel:
    """A fake provider model that always succeeds, recording what it saw."""

    def __init__(self, key):
        self.key = key
        self.seen = None

    def invoke(self, input, config=None, **kwargs):
        self.seen = input
        return {"served_by": self.key, "input": input}

    async def ainvoke(self, input, config=None, **kwargs):
        self.seen = input
        return {"served_by": self.key, "input": input}

    def stream(self, input, config=None, **kwargs):
        self.seen = input
        yield {"served_by": self.key, "chunk": 1}
        yield {"served_by": self.key, "chunk": 2}


class _BoomModel:
    """A fake provider model that raises on invoke/stream."""

    def __init__(self, key, exc):
        self.key = key
        self._exc = exc

    def invoke(self, input, config=None, **kwargs):
        raise self._exc

    async def ainvoke(self, input, config=None, **kwargs):
        raise self._exc

    def stream(self, input, config=None, **kwargs):
        raise self._exc
        yield  # pragma: no cover


class _Transient(Exception):
    """Duck-typed transient error (has a status_code the classifier recognises)."""

    status_code = 503


def _inject(monkeypatch, models: dict):
    """Patch build_chat_model so each provider key yields its fake model."""
    def fake_build(provider_key=None, model=None, **kwargs):
        return models[provider_key]

    monkeypatch.setattr("eklavya.providers.build_chat_model", fake_build)


# --- fallback_order ---------------------------------------------------------


def test_order_default_first_then_rest(monkeypatch):
    _configure(monkeypatch, "glm", "minimax", "qwen")
    assert fallback_order()[0] == "glm"
    assert set(fallback_order()) == {"glm", "minimax", "qwen"}


def test_order_requested_provider_leads(monkeypatch):
    _configure(monkeypatch, "glm", "minimax", "qwen")
    order = fallback_order("qwen")
    assert order[0] == "qwen"
    assert set(order) == {"glm", "minimax", "qwen"}


def test_order_single_provider_is_length_one(monkeypatch):
    _configure(monkeypatch, "minimax")
    assert fallback_order() == ["minimax"]


def test_order_falls_back_when_default_not_configured(monkeypatch):
    _configure(monkeypatch, "qwen")  # default 'glm' not configured
    assert fallback_order()[0] == "qwen"


# --- error classification ---------------------------------------------------


def test_is_transient_recognises_status_and_network_and_keywords():
    assert is_transient(_Transient("down"))
    assert is_transient(ConnectionError("refused"))
    assert is_transient(TimeoutError("slow"))
    assert is_transient(Exception("Rate limit exceeded (429)"))
    assert is_transient(Exception("service temporarily unavailable"))


def test_is_transient_ignores_programming_errors():
    assert not is_transient(TypeError("bad arg"))
    assert not is_transient(KeyError("missing"))
    assert not is_transient(Exception("malformed prompt template"))


# --- the fallback loop ------------------------------------------------------


def test_returns_on_first_success(monkeypatch):
    _configure(monkeypatch, "glm", "minimax")
    ok = _OKModel("glm")
    _inject(monkeypatch, {"glm": ok, "minimax": _OKModel("minimax")})
    model = build_fallback_chat_model()
    out = model.invoke("hello")
    assert out["served_by"] == "glm"  # never touched the fallback
    assert ok.seen == "hello"


def test_hops_to_next_provider_on_transient_error(monkeypatch):
    _configure(monkeypatch, "glm", "minimax")
    served = _OKModel("minimax")
    _inject(monkeypatch, {
        "glm": _BoomModel("glm", _Transient("rate limited")),
        "minimax": served,
    })
    model = build_fallback_chat_model()
    out = model.invoke("teach me recursion")
    assert out["served_by"] == "minimax"                 # hopped past the down provider
    assert served.seen == "teach me recursion"           # same messages replayed


def test_hops_across_multiple_down_providers(monkeypatch):
    _configure(monkeypatch, "glm", "minimax", "qwen")
    _inject(monkeypatch, {
        "glm": _BoomModel("glm", _Transient("429")),
        "minimax": _BoomModel("minimax", ConnectionError("refused")),
        "qwen": _OKModel("qwen"),
    })
    model = build_fallback_chat_model()  # chain glm -> minimax -> qwen
    assert model.invoke("x")["served_by"] == "qwen"


def test_raises_clear_aggregate_error_when_all_fail(monkeypatch):
    _configure(monkeypatch, "glm", "minimax")
    _inject(monkeypatch, {
        "glm": _BoomModel("glm", _Transient("glm down")),
        "minimax": _BoomModel("minimax", ConnectionError("minimax down")),
    })
    model = build_fallback_chat_model()
    with pytest.raises(AllProvidersFailed) as ei:
        model.invoke("x")
    msg = str(ei.value)
    assert "glm" in msg and "minimax" in msg               # names both failed providers
    assert len(ei.value.errors) == 2


def test_non_transient_error_propagates_without_hopping(monkeypatch):
    _configure(monkeypatch, "glm", "minimax")
    reached = _OKModel("minimax")
    _inject(monkeypatch, {
        "glm": _BoomModel("glm", TypeError("real bug in request")),
        "minimax": reached,
    })
    model = build_fallback_chat_model()
    with pytest.raises(TypeError):
        model.invoke("x")
    assert reached.seen is None                            # fallback NOT tried on a real bug


def test_single_provider_unchanged_success(monkeypatch):
    _configure(monkeypatch, "glm")
    ok = _OKModel("glm")
    _inject(monkeypatch, {"glm": ok})
    model = build_fallback_chat_model()
    assert model.chain == ["glm"]
    assert model.invoke("x")["served_by"] == "glm"


def test_single_provider_transient_error_still_raises(monkeypatch):
    _configure(monkeypatch, "glm")
    _inject(monkeypatch, {"glm": _BoomModel("glm", _Transient("down"))})
    model = build_fallback_chat_model()
    with pytest.raises(AllProvidersFailed):
        model.invoke("x")


def test_streaming_hops_when_first_provider_fails(monkeypatch):
    _configure(monkeypatch, "glm", "minimax")
    _inject(monkeypatch, {
        "glm": _BoomModel("glm", _Transient("down")),
        "minimax": _OKModel("minimax"),
    })
    model = build_fallback_chat_model()
    chunks = list(model.stream("go"))
    assert [c["served_by"] for c in chunks] == ["minimax", "minimax"]


async def test_async_invoke_hops(monkeypatch):
    _configure(monkeypatch, "glm", "minimax")
    _inject(monkeypatch, {
        "glm": _BoomModel("glm", _Transient("down")),
        "minimax": _OKModel("minimax"),
    })
    model = build_fallback_chat_model()
    out = await model.ainvoke("x")
    assert out["served_by"] == "minimax"


# --- bind_tools / bind preservation ----------------------------------------


class _BindableModel:
    """Records bind_tools/bind, and reports what was bound when invoked."""

    def __init__(self, key):
        self.key = key
        self.tools = None
        self.bound = {}

    def bind_tools(self, tools, **kwargs):
        self.tools = list(tools)
        return self

    def bind(self, **kwargs):
        self.bound.update(kwargs)
        return self

    def invoke(self, input, config=None, **kwargs):
        return {"served_by": self.key, "tools": self.tools, "bound": self.bound}


def test_bind_tools_is_replayed_on_the_serving_provider(monkeypatch):
    _configure(monkeypatch, "glm", "minimax")
    glm, mm = _BindableModel("glm"), _BindableModel("minimax")
    _inject(monkeypatch, {"glm": glm, "minimax": mm})
    model = build_fallback_chat_model()
    bound = model.bind_tools(["tool_a", "tool_b"]).bind(temperature=0)
    assert isinstance(bound, FallbackChatModel)           # still a chat model, fallback intact
    out = bound.invoke("x")
    assert out["served_by"] == "glm"
    assert out["tools"] == ["tool_a", "tool_b"]           # tools reached the provider
    assert out["bound"] == {"temperature": 0}


def test_bind_tools_replayed_on_fallback_provider_too(monkeypatch):
    _configure(monkeypatch, "glm", "minimax")

    class _BoomBindable(_BindableModel):
        def invoke(self, input, config=None, **kwargs):
            raise _Transient("glm down")

    glm, mm = _BoomBindable("glm"), _BindableModel("minimax")
    _inject(monkeypatch, {"glm": glm, "minimax": mm})
    model = build_fallback_chat_model()
    out = model.bind_tools(["t1"]).invoke("x")
    assert out["served_by"] == "minimax"
    assert mm.tools == ["t1"]                             # tools replayed on the fallback


# --- sticky, cache-friendly balancer ---------------------------------------


def test_priority_order_qwen_kimi_glm_minimax(monkeypatch):
    _configure(monkeypatch, "glm", "minimax", "qwen", "kimi")
    # All four configured → the explicit priority order is honoured.
    assert priority_order() == ["qwen", "kimi", "glm", "minimax"]
    # Intersected with only the configured subset, order preserved.
    monkeypatch.delenv("EKLAVYA_QWEN_API_KEY", raising=False)
    assert priority_order() == ["kimi", "glm", "minimax"]


def test_priority_order_configurable(monkeypatch):
    _configure(monkeypatch, "glm", "minimax", "qwen", "kimi")
    monkeypatch.setattr(config, "PROVIDER_ORDER", ["minimax", "glm", "kimi", "qwen"])
    assert priority_order() == ["minimax", "glm", "kimi", "qwen"]


def test_sticky_stays_on_primary_across_many_requests(monkeypatch):
    """Cache-preserving: with the primary healthy, EVERY request lands on the same provider."""
    _configure(monkeypatch, "qwen", "kimi", "glm")
    served = {k: _OKModel(k) for k in ("qwen", "kimi", "glm")}
    _inject(monkeypatch, served)
    model = build_fallback_chat_model()  # sticky-auto
    picks = [model.invoke("x")["served_by"] for _ in range(20)]
    assert picks == ["qwen"] * 20  # never left the warm primary


def test_sticky_advances_and_sticks_on_primary_exhaustion(monkeypatch):
    """On the primary exhausting, advance to the next priority provider AND stay there."""
    _configure(monkeypatch, "qwen", "kimi", "glm")
    boom_then = {"qwen": _BoomModel("qwen", _Transient("429")),
                 "kimi": _OKModel("kimi"), "glm": _OKModel("glm")}
    _inject(monkeypatch, boom_then)
    model = build_fallback_chat_model()
    # first request: qwen fails (transient) → fails over to kimi this request AND cools qwen.
    assert model.invoke("a")["served_by"] == "kimi"
    # qwen is now cooling down → every subsequent request STICKS to kimi (no retry of qwen).
    assert [model.invoke("x")["served_by"] for _ in range(10)] == ["kimi"] * 10


def test_cooldown_expiry_restores_eligibility(monkeypatch):
    _configure(monkeypatch, "qwen", "kimi")
    monkeypatch.setattr(config, "PROVIDER_COOLDOWN", 300)
    # qwen cooled down at t=0 → chain leads with kimi during the cooldown window…
    fallback.mark_cooldown("qwen", now=0.0)
    assert sticky_chain(None, now=100.0)[0] == "kimi"
    # …and once the cooldown elapses, qwen is eligible again as the highest priority. Since the
    # current sticky (kimi) is still eligible we DON'T flap back mid-session…
    assert sticky_chain(None, now=400.0)[0] == "kimi"
    # …but if kimi then cools down too, we recompute to the now-eligible highest-priority qwen.
    fallback.mark_cooldown("kimi", now=400.0)
    assert sticky_chain(None, now=800.0)[0] == "qwen"


def test_no_flapping_when_current_sticky_still_eligible(monkeypatch):
    _configure(monkeypatch, "qwen", "kimi", "glm")
    # kimi is chosen sticky (qwen cooling); when qwen recovers we keep kimi (no needless switch).
    fallback.mark_cooldown("qwen", now=0.0)
    assert sticky_chain(None, now=10.0)[0] == "kimi"
    assert sticky_chain(None, now=1000.0)[0] == "kimi"  # qwen eligible again, but no flap


def test_single_request_fails_over_through_whole_chain(monkeypatch):
    """A single request still tries EVERY configured provider before giving up."""
    _configure(monkeypatch, "qwen", "kimi", "glm", "minimax")
    _inject(monkeypatch, {
        "qwen": _BoomModel("qwen", _Transient("down")),
        "kimi": _BoomModel("kimi", ConnectionError("refused")),
        "glm": _BoomModel("glm", _Transient("503")),
        "minimax": _OKModel("minimax"),
    })
    model = build_fallback_chat_model()
    assert model.invoke("x")["served_by"] == "minimax"  # reached the tail of the chain


def test_single_configured_provider_is_chain_of_length_one(monkeypatch):
    _configure(monkeypatch, "glm")
    ok = _OKModel("glm")
    _inject(monkeypatch, {"glm": ok})
    model = build_fallback_chat_model()
    assert model.chain == ["glm"]
    assert model.invoke("x")["served_by"] == "glm"


def test_explicit_pin_leads_with_that_provider(monkeypatch):
    _configure(monkeypatch, "qwen", "kimi", "glm")
    _inject(monkeypatch, {k: _OKModel(k) for k in ("qwen", "kimi", "glm")})
    model = build_fallback_chat_model("glm")  # pinned to glm despite qwen being higher priority
    assert [model.invoke("x")["served_by"] for _ in range(5)] == ["glm"] * 5


def test_explicit_pin_fails_over_and_returns_when_pinned_recovers(monkeypatch):
    _configure(monkeypatch, "qwen", "kimi", "glm")
    # pinned to qwen; qwen cooling down → leads with next-priority kimi for now.
    fallback.mark_cooldown("qwen", now=0.0)
    assert sticky_chain("qwen", now=10.0)[0] == "kimi"
    # once qwen's cooldown elapses, the PIN reasserts qwen as the lead (unlike auto's no-flap).
    assert sticky_chain("qwen", now=1000.0)[0] == "qwen"
