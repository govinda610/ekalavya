"""Per-user data isolation (multi-user Phase 1).

Proves the contextvar-driven ``config.paths()`` accessor keeps two users' state fully
separate: setting the current home to A then B routes every state function (db, profile,
ratings, XP, backups, settings, chats) into that user's own files, with zero bleed.

Fully offline, temp homes only — the real ~/.eklavya is never touched. We import with a
throwaway EKLAVYA_HOME so even module import can't reach the real data.
"""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="eklavya-iso-")
os.environ["EKLAVYA_HOME"] = _TMP

import pytest  # noqa: E402

from eklavya import backups as bk  # noqa: E402
from eklavya import chatstore, config, progress, settings, tools  # noqa: E402
from eklavya.db import connect, init_db  # noqa: E402

HOME_A = Path(tempfile.mkdtemp(prefix="eklavya-A-"))
HOME_B = Path(tempfile.mkdtemp(prefix="eklavya-B-"))


@contextmanager
def as_user(home: Path):
    """Bind the current context to a user's home, then restore it (contextvars.reset)."""
    from eklavya.config import _current_home

    token = _current_home.set(home)
    try:
        config.ensure_home()
        init_db()
        yield
    finally:
        _current_home.reset(token)


# --- paths() resolves per-context ------------------------------------------

def test_paths_resolve_per_context():
    with as_user(HOME_A):
        pa = config.paths()
        assert pa.home == HOME_A
        assert pa.db == HOME_A / "workspace" / "eklavya.db"
        assert pa.profile == HOME_A / "workspace" / "profile.md"
        assert pa.checkpoints == HOME_A / "checkpoints.sqlite"
        assert pa.backups == HOME_A / "backups"
    with as_user(HOME_B):
        assert config.paths().home == HOME_B
        assert config.paths().db == HOME_B / "workspace" / "eklavya.db"


def test_config_shims_track_the_contextvar():
    # the legacy module constants must follow the current context too
    with as_user(HOME_A):
        assert config.DB_PATH == HOME_A / "workspace" / "eklavya.db"
        assert config.EKLAVYA_HOME == HOME_A
    with as_user(HOME_B):
        assert config.DB_PATH == HOME_B / "workspace" / "eklavya.db"


# --- profile isolation ------------------------------------------------------

def test_profile_is_per_user():
    with as_user(HOME_A):
        tools.save_profile("# A's profile\nalpha")
    with as_user(HOME_B):
        assert tools.read_profile() == "(no profile yet — treat this as a first-time learner)"
        tools.save_profile("# B's profile\nbravo")
    # each user still sees only their own
    with as_user(HOME_A):
        assert tools.read_profile() == "# A's profile\nalpha"
    with as_user(HOME_B):
        assert tools.read_profile() == "# B's profile\nbravo"
    # and they live in different files
    assert (HOME_A / "workspace" / "profile.md").read_text() == "# A's profile\nalpha"
    assert (HOME_B / "workspace" / "profile.md").read_text() == "# B's profile\nbravo"


# --- db / ratings / XP isolation -------------------------------------------

def test_ratings_and_xp_are_per_user():
    with as_user(HOME_A):
        tools.set_baseline_rating("LangGraph", "debugging", "strong")
        progress.award_xp(100, label="a")
    with as_user(HOME_B):
        # B's fresh db has none of A's ratings
        conn = connect()
        try:
            n = conn.execute("SELECT COUNT(*) AS c FROM ratings").fetchone()["c"]
        finally:
            conn.close()
        assert n == 0
        assert progress.stats()["xp"] == 0
        tools.set_baseline_rating("Python", "syntax_recall", "gap")
        progress.award_xp(25, label="b")
    # A is untouched by B's writes
    with as_user(HOME_A):
        assert "LangGraph / debugging: strong" in tools.mastery_summary()
        assert "Python" not in tools.mastery_summary()
        assert progress.stats()["xp"] == 100
    with as_user(HOME_B):
        assert progress.stats()["xp"] == 25


# --- chats / checkpointer isolation ----------------------------------------

def test_chats_are_per_user():
    with as_user(HOME_A):
        chatstore.touch_chat("thread-A", mode="practice", title="A chat")
    with as_user(HOME_B):
        assert chatstore.list_chats() == []  # B sees none of A's chats
        chatstore.touch_chat("thread-B", mode="mock", title="B chat")
    with as_user(HOME_A):
        titles = {c["title"] for c in chatstore.list_chats()}
        assert titles == {"A chat"}
    with as_user(HOME_B):
        titles = {c["title"] for c in chatstore.list_chats()}
        assert titles == {"B chat"}


# --- settings isolation -----------------------------------------------------

def test_settings_are_per_user():
    with as_user(HOME_A):
        settings.set_death_on_cheat(False)
    with as_user(HOME_B):
        assert settings.get_death_on_cheat() is True  # B keeps the default
        settings.set_death_on_cheat(True)
    with as_user(HOME_A):
        assert settings.get_death_on_cheat() is False
    assert (HOME_A / "settings.json").exists()
    assert (HOME_B / "settings.json").exists()


# --- backups isolation ------------------------------------------------------

def test_backups_snapshot_the_right_user():
    with as_user(HOME_A):
        tools.save_profile("A-state")
        snap_a = bk.snapshot("A")
        assert (HOME_A / "backups" / snap_a).exists()
    with as_user(HOME_B):
        # B's backups dir is separate and doesn't contain A's snapshot
        assert bk.list_snapshots() == []
        assert not (HOME_B / "backups" / snap_a).exists()


# --- thread ownership (multi-user) ------------------------------------------

def test_thread_ownership_blocks_cross_user(monkeypatch):
    """When deployed, a chat row stamped with a different owner is not owned.

    (Per-user DBs already isolate; this ownership check is the explicit defense-in-depth
    guard for a row that *does* resolve in the current DB but belongs to someone else —
    e.g. a future shared/consolidated table. We simulate that by stamping the row's
    user_id directly, then querying ownership as a different user.)"""
    monkeypatch.setattr(config, "DEPLOYED", True)
    data_root = Path(tempfile.mkdtemp(prefix="eklavya-mu-"))
    home_a = data_root / "users" / "uid-a"

    with as_user(home_a):
        # user A creates a thread → stamped with uid-a
        chatstore.touch_chat("owned-by-a", mode="practice")
        assert chatstore.current_user_id() == "uid-a"
        assert chatstore.owns_thread("owned-by-a") is True

        # a row owned by someone else, present in this DB → not owned, and a brand-new
        # thread → claimable
        conn = connect()
        try:
            conn.execute(
                "INSERT INTO chats(thread_id, user_id) VALUES('owned-by-b', 'uid-b')"
            )
            conn.commit()
        finally:
            conn.close()
        assert chatstore.owns_thread("owned-by-b") is False   # cross-user → blocked
        assert chatstore.owns_thread("never-seen") is True     # new thread → claimable


def test_webapp_returns_404_for_foreign_thread(monkeypatch):
    """The route-level ownership guard 404s a chat the current user doesn't own."""
    from starlette.testclient import TestClient

    from eklavya.webapp import create_app

    monkeypatch.setattr(config, "DEPLOYED", True)
    # multi-user create_app() now mounts auth: needs a signing secret + a data root so the
    # session's uid resolves to the home we seed. Sign a cookie for uid-x directly.
    monkeypatch.setenv("EKLAVYA_SECRET_KEY", "test-secret-please-ignore-0123456789abcdef")
    monkeypatch.setenv("EKLAVYA_INSECURE_COOKIES", "1")
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", tempfile.mkdtemp(prefix="eklavya-web-mu-"))
    # uid-x must be a real account, else the auth middleware rejects the cookie (N4).
    from eklavya import auth
    _u = auth._connect()
    _u.execute("INSERT INTO users(id, email, password_hash) VALUES('uid-x', 'x@eklavya.dev', 'x')")
    _u.commit()
    _u.close()
    home = config.user_home("uid-x")
    from eklavya.config import _current_home

    token = _current_home.set(home)
    try:
        config.ensure_home()
        init_db()
        # one thread owned by the current user, one owned by someone else
        chatstore.touch_chat("mine", mode="practice", title="mine")
        conn = connect()
        try:
            conn.execute("INSERT INTO chats(thread_id, user_id) VALUES('theirs', 'uid-other')")
            conn.commit()
        finally:
            conn.close()
    finally:
        _current_home.reset(token)

    from starlette.responses import Response

    from eklavya.middleware import issue_session

    r = Response()  # capture a validly-signed session cookie for uid-x
    issue_session(r, "uid-x")
    signed = r.headers["set-cookie"].split("eklavya_session=")[1].split(";")[0]

    c = TestClient(create_app())
    c.cookies.set("eklavya_session", signed)
    assert c.get("/api/chats/mine").status_code == 200
    assert c.get("/api/chats/theirs").status_code == 404
    assert c.patch("/api/chats/theirs", json={"title": "hijack"}).status_code == 404


def test_ownership_is_noop_in_single_user():
    # default single-user mode: no ownership enforcement (user_id stays NULL)
    assert config.DEPLOYED is False
    with as_user(HOME_A):
        chatstore.touch_chat("single-thread", mode="practice")
        assert chatstore.owns_thread("single-thread") is True
        assert chatstore.owns_thread("anything") is True
        assert chatstore.current_user_id() is None


# --- read confinement (SECURITY_AUDIT F1 + F5) -----------------------------

def test_multiuser_read_is_confined_to_own_tree(monkeypatch):
    """In multi-user mode the agent's read backend must not reach another user's
    home, the shared users.db, or the host — only this user's own workspace."""
    from eklavya import workspace

    monkeypatch.setattr(config, "DEPLOYED", True)
    with as_user(HOME_A):
        # own workspace: allowed
        assert workspace._is_forbidden(str(HOME_A / "workspace" / "profile.md")) is False
        # own app internals (backups/checkpoints): forbidden
        assert workspace._is_forbidden(str(HOME_A / "checkpoints.sqlite")) is True
        # another user's home + workspace: forbidden (the F1 cross-tenant leak)
        assert workspace._is_forbidden(str(HOME_B / "workspace" / "profile.md")) is True
        # a sibling users.db next to the homes: forbidden
        assert workspace._is_forbidden(str(HOME_B.parent / "users.db")) is True
        # arbitrary host path: forbidden
        assert workspace._is_forbidden("/etc/passwd") is True


def test_sibling_prefix_cannot_bypass_workspace_check(monkeypatch):
    """F5: `workspace-evil` must not pass the `workspace` prefix check."""
    from eklavya import workspace

    monkeypatch.setattr(config, "DEPLOYED", True)
    with as_user(HOME_A):
        ws = HOME_A / "workspace"
        evil = ws.parent / (ws.name + "-evil")  # e.g. .../workspace-evil
        evil.mkdir(parents=True, exist_ok=True)
        (evil / "secret.txt").write_text("nope")
        assert workspace._is_forbidden(str(evil / "secret.txt")) is True


def test_single_user_still_reads_host_broadly(monkeypatch):
    """Regression: the self-host single-user path keeps broad host reads (minus secrets)."""
    from eklavya import workspace

    assert config.DEPLOYED is False
    with as_user(HOME_A):
        # a normal host file is readable in single-user mode
        assert workspace._is_forbidden(str(Path.home() / "somefile.txt")) is False
        # but the secret dirs stay forbidden
        assert workspace._is_forbidden(str(Path.home() / ".ssh" / "id_rsa")) is True
