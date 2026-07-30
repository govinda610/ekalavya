"""Web app route tests (no live model — just wiring + rendering)."""

import os
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-web-")
os.environ["EKLAVYA_HOME"] = _TMP
os.environ["EKLAVYA_PROFILE"] = str(Path(_TMP) / "profile.md")

import pytest  # noqa: E402

from eklavya import tools  # noqa: E402
from eklavya.db import init_db  # noqa: E402
from eklavya.webapp import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def seeded():
    from eklavya import config as _cfg  # reset the REAL db (shared across test files)
    db = _cfg.DB_PATH
    if db.exists():
        db.unlink()
    init_db()
    tools.set_baseline_rating("FastAPI", "debugging", "gap")
    yield


def test_index_serves_the_spa():
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    r = c.get("/")
    assert r.status_code == 200
    assert "EKALAVYA" in r.text and "Practice" in r.text and "monaco-editor" in r.text


def test_dashboard_and_apis():
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    assert c.get("/dashboard").status_code == 200
    assert "FastAPI" in c.get("/dashboard").text
    ov = c.get("/api/overview")
    assert ov.status_code == 200 and "FastAPI" in ov.json()["grid"]["pillars"]
    cfg = c.get("/api/config").json()
    assert "practice" in cfg["kickoff"] and "provider" in cfg


def test_config_includes_first_run_and_onboard():
    from starlette.testclient import TestClient

    from eklavya import config
    from eklavya.db import connect

    client = TestClient(create_app())
    # seeded fixture added a rating -> not a first run
    assert client.get("/api/config").json()["first_run"] is False
    assert "onboard" in client.get("/api/config").json()["kickoff"]
    # wipe ratings + profile -> first run
    conn = connect()
    conn.execute("DELETE FROM ratings")
    conn.commit()
    conn.close()
    if config.PROFILE_PATH.exists():
        config.PROFILE_PATH.unlink()
    assert client.get("/api/config").json()["first_run"] is True


def test_profile_view_and_edit_roundtrip():
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    # the page renders with the editor textarea + the mastery map (seeded FastAPI pillar)
    page = c.get("/profile")
    assert page.status_code == 200
    assert 'id="pedit"' in page.text and "Mastery map" in page.text and "FastAPI" in page.text
    # starts empty, saves, and reads back
    assert c.get("/api/profile").json()["text"] == ""
    c.put("/api/profile", json={"text": "# Me\n\n- goal: **PhD at ETH**"})
    assert "ETH" in c.get("/api/profile").json()["text"]
    # the rendered page embeds the saved markdown (recoverable from the textarea)
    assert "PhD at ETH" in c.get("/profile").text


def test_settings_toggle_persists_and_shows_in_config():
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    assert c.get("/api/config").json()["death_on_cheat"] is True  # default on
    assert c.put("/api/settings", json={"death_on_cheat": False}).json()["death_on_cheat"] is False
    assert c.get("/api/config").json()["death_on_cheat"] is False  # persisted
    c.put("/api/settings", json={"death_on_cheat": True})          # restore for other tests


def test_death_and_reclaim_endpoints():
    from starlette.testclient import TestClient

    from eklavya import progress

    c = TestClient(create_app())
    progress.award_xp(80)
    st = c.get("/api/stats").json()
    assert st["xp"] >= 80
    pen = c.post("/api/penalise").json()
    assert pen["lost"] > 0 and pen["stats"]["streak"] == 0  # souls dropped, streak broken
    rec = c.post("/api/reclaim").json()
    assert rec["reclaimed"] == pen["lost"]  # typed-it-yourself reclaims the drop


def test_artifacts_crud_endpoints():
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    # empty to start
    assert c.get("/api/artifacts").json() == []
    # create
    a = c.post("/api/artifacts", json={"title": "Recursion", "kind": "markdown",
                                       "content": "# base case"}).json()
    aid = a["id"]
    assert a["title"] == "Recursion" and a["kind"] == "markdown"
    # get
    got = c.get(f"/api/artifacts/{aid}").json()
    assert got["content"] == "# base case"
    assert c.get("/api/artifacts/99999").status_code == 404
    # list + filter + search
    c.post("/api/artifacts", json={"title": "tree.py", "kind": "code", "content": "def f(): pass"})
    assert len(c.get("/api/artifacts").json()) == 2
    assert [x["kind"] for x in c.get("/api/artifacts?kind=code").json()] == ["code"]
    assert len(c.get("/api/artifacts?q=Recursion").json()) == 1
    # patch (pin)
    patched = c.patch(f"/api/artifacts/{aid}", json={"pinned": True, "content": "# updated"}).json()
    assert patched["pinned"] is True and patched["content"] == "# updated"
    assert c.patch("/api/artifacts/99999", json={"title": "x"}).status_code == 404
    # pinned floats first
    assert c.get("/api/artifacts").json()[0]["id"] == aid
    # delete
    assert c.delete(f"/api/artifacts/{aid}").json() == {"ok": True}
    assert c.get(f"/api/artifacts/{aid}").status_code == 404
    assert c.delete(f"/api/artifacts/{aid}").status_code == 404


def test_fonts_are_vendored_and_served_locally():
    """#35 — pages link the local /static/fonts.css (no Google Fonts CDN), and the CSS +
    its woff2 files are actually served."""
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    for path in ("/", "/dashboard", "/journey", "/profile"):
        html = c.get(path).text
        assert "/static/fonts.css" in html, f"{path} should link the vendored stylesheet"
        assert "fonts.googleapis.com" not in html and "fonts.gstatic.com" not in html, \
            f"{path} still references the Google Fonts CDN"
    css = c.get("/static/fonts.css")
    assert css.status_code == 200 and "@font-face" in css.text
    # every woff2 the CSS points at is actually reachable
    import re
    for rel in sorted(set(re.findall(r"/static/fonts/[\w.-]+\.woff2", css.text))):
        assert c.get(rel).status_code == 200, f"missing font file {rel}"


def test_truncate_rewinds_thread_state():
    """#36 — /api/truncate drops trailing turns from the checkpointed thread so rewind/edit
    keep the UI and server in lock-step. keep_user_turns=N leaves the first N human turns."""
    from starlette.testclient import TestClient

    from langchain_core.messages import AIMessage, HumanMessage

    from eklavya.agent import build_agent
    from eklavya.prompts import SESSION
    from eklavya.tools import SESSION_TOOLS

    c = TestClient(create_app())
    # Seed a thread's checkpointer with two full exchanges (the same persistent saver the
    # route resolves, since agent_for uses the default checkpointer).
    agent = build_agent(SESSION, SESSION_TOOLS)
    thread = "rewind-test-thread"
    cfg = {"configurable": {"thread_id": thread}}
    agent.update_state(cfg, {"messages": [
        HumanMessage("q1", id="h1"), AIMessage("a1", id="a1"),
        HumanMessage("q2", id="h2"), AIMessage("a2", id="a2"),
    ]})

    def _human_texts():
        msgs = (agent.get_state(cfg).values or {}).get("messages", [])
        return [m.content for m in msgs if getattr(m, "type", None) == "human"]

    assert _human_texts() == ["q1", "q2"]
    # keep only the first turn (rewind of the last exchange)
    r = c.post("/api/truncate", json={"thread": thread, "keep_user_turns": 1})
    assert r.status_code == 200 and r.json()["removed"] == 2  # q2 + a2 dropped
    assert _human_texts() == ["q1"]
    # keeping more than exist is a harmless no-op
    r = c.post("/api/truncate", json={"thread": thread, "keep_user_turns": 5})
    assert r.json()["removed"] == 0 and _human_texts() == ["q1"]
    # keep none clears the whole conversation
    r = c.post("/api/truncate", json={"thread": thread, "keep_user_turns": 0})
    assert r.json()["removed"] == 2 and _human_texts() == []


def test_selfcheck_receives_sandbox_run_output(monkeypatch):
    """#54 — the hallucination judge's context is enriched with the turn's actual sandbox
    output (grade_and_record / run_bash results), so it can catch a reply that contradicts
    what the code really printed."""
    from starlette.testclient import TestClient

    from eklavya import agent as agent_mod, verify

    # A fake agent whose stream yields one grade_and_record tool result then the tutor's
    # (wrong) claim. get_state → no interrupt, so the run completes and selfcheck fires.
    class _Chunk:
        def __init__(self, type=None, name="", content="", tool_call_chunks=None):
            self.type = type; self.name = name; self.content = content
            self.tool_call_chunks = tool_call_chunks

    class _State:
        interrupts = ()

    class _FakeAgent:
        def stream(self, inputs, config=None, stream_mode=None):
            yield _Chunk(type="tool", name="grade_and_record",
                         content="FAIL: expected 6 but the learner's code printed 5"), {}
            yield _Chunk(content="Your code correctly prints 6 — great job."), {}
        def get_state(self, config):
            return _State()

    monkeypatch.setattr(agent_mod, "build_agent", lambda *a, **k: _FakeAgent())

    captured = {}

    def _fake_selfcheck(reply, context=""):
        captured["reply"] = reply
        captured["context"] = context
        return None  # don't append a note; we only assert the context it received

    monkeypatch.setattr(verify, "selfcheck", _fake_selfcheck)

    c = TestClient(create_app())
    # drain the stream so _events runs to completion (and calls selfcheck)
    with c.stream("POST", "/api/stream",
                  json={"mode": "practice", "thread": "sc-test", "text": "does this print 6?"}) as r:
        for _ in r.iter_lines():
            pass

    assert "ACTUAL CODE EXECUTION OUTPUT" in captured["context"]
    assert "printed 5" in captured["context"]              # the real sandbox result reached the judge
    assert "does this print 6?" in captured["context"]     # the learner's message is still there
    assert "prints 6" in captured["reply"]                 # and the tutor's claim is what's judged


def test_client_ip_honours_xff_only_when_proxy_trusted():
    """#52 — behind a trusted proxy we key throttling on the left-most X-Forwarded-For
    entry (the real client); otherwise we ignore the header and use request.client.host
    so a direct client can't spoof it."""
    from eklavya import config, webapp

    class _FakeReq:
        def __init__(self, host, xff=None):
            self.client = type("C", (), {"host": host})()
            self.headers = {"x-forwarded-for": xff} if xff is not None else {}

    proxy_ip, real_ip = "10.0.0.1", "203.0.113.7"
    req = _FakeReq(proxy_ip, xff=f"{real_ip}, 10.0.0.1")

    orig = config.TRUST_PROXY
    try:
        # not trusted → the header is ignored, we use the connecting (proxy) address
        config.TRUST_PROXY = False
        assert webapp.client_ip(req) == proxy_ip
        # trusted → the left-most (original client) entry wins
        config.TRUST_PROXY = True
        assert webapp.client_ip(req) == real_ip
        # trusted but no header → fall back to request.client.host
        assert webapp.client_ip(_FakeReq(proxy_ip)) == proxy_ip
        assert webapp.client_ip(_FakeReq(proxy_ip, xff="")) == proxy_ip
    finally:
        config.TRUST_PROXY = orig


def test_settings_get_and_put():
    from starlette.testclient import TestClient

    c = TestClient(create_app())
    s = c.get("/api/settings").json()
    assert "death_on_cheat" in s and "reduced_motion" in s and "guru_voice" in s
    assert isinstance(s["providers"], list) and s["providers"]
    keys = {p["key"] for p in s["providers"]}
    assert {"glm", "minimax", "qwen", "kimi"} <= keys
    # update several prefs at once
    r = c.put("/api/settings", json={"reduced_motion": True, "guru_voice": False}).json()
    assert r["reduced_motion"] is True and r["guru_voice"] is False
    assert c.get("/api/settings").json()["reduced_motion"] is True   # persisted
    # legacy shape still works
    c.put("/api/settings", json={"death_on_cheat": True, "reduced_motion": False, "guru_voice": True})
