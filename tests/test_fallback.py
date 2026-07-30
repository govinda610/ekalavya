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

from eklavya import fallback  # noqa: E402
from eklavya.fallback import (  # noqa: E402
    AllProvidersFailed,
    FallbackChatModel,
    build_fallback_chat_model,
    fallback_order,
    is_transient,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _ALL_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EKLAVYA_PROVIDER", "glm")
    monkeypatch.delenv("EKLAVYA_BALANCE", raising=False)
    # reset the round-robin cursor so rotation tests are deterministic
    fallback._rr = __import__("itertools").count()
    yield


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


# --- load-balancing (round-robin) ------------------------------------------


def test_round_robin_rotates_entry_provider(monkeypatch):
    _configure(monkeypatch, "glm", "minimax", "qwen")
    monkeypatch.setenv("EKLAVYA_BALANCE", "1")
    leads = [build_fallback_chat_model().chain[0] for _ in range(3)]
    # Three configured providers, three sessions → each leads once (in some order).
    assert set(leads) == {"glm", "minimax", "qwen"}
    # Every session still has the full chain as its fallback set.
    assert all(set(build_fallback_chat_model().chain) == {"glm", "minimax", "qwen"}
               for _ in range(3))


def test_balancing_off_by_default_keeps_default_first(monkeypatch):
    _configure(monkeypatch, "glm", "minimax", "qwen")
    # No EKLAVYA_BALANCE → default provider leads every time.
    assert all(build_fallback_chat_model().chain[0] == "glm" for _ in range(3))


def test_explicit_provider_is_honoured_even_with_balancing(monkeypatch):
    _configure(monkeypatch, "glm", "minimax", "qwen")
    monkeypatch.setenv("EKLAVYA_BALANCE", "1")
    # An explicit request pins the leader regardless of round-robin.
    assert all(build_fallback_chat_model("minimax").chain[0] == "minimax" for _ in range(3))


def test_single_provider_no_rotation(monkeypatch):
    _configure(monkeypatch, "glm")
    monkeypatch.setenv("EKLAVYA_BALANCE", "1")
    assert build_fallback_chat_model().chain == ["glm"]
