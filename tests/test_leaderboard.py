"""Opt-in, privacy-safe leaderboard (deployed multi-user).

Fully offline. Every test uses a throwaway EKLAVYA_DATA_ROOT + a test signing secret and
forces DEPLOYED mode, so the real ~/.eklavya / ~/.eklavya-data and the user's real accounts
are never touched. Proves: the additive migration leaves existing data intact; opt-in flips
a user absent→present and opt-out removes them; non-opted-in users never appear; handle
uniqueness is case-insensitive; every column sorts; the Eklavya Score is deterministic; a
2-user aggregation binds/restores homes (tenant isolation preserved); and NO route ever
leaks email / real name — a row carries only the handle + numeric fields.
"""

import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def mu(monkeypatch):
    """Multi-user mode with an isolated data root + test secret."""
    from eklavya import auth, config, leaderboard

    root = Path(tempfile.mkdtemp(prefix="eklavya-lb-"))
    monkeypatch.setenv("EKLAVYA_DATA_ROOT", str(root))
    monkeypatch.setenv("EKLAVYA_SECRET_KEY", "test-secret-please-ignore-0123456789abcdef")
    monkeypatch.setenv("EKLAVYA_INSECURE_COOKIES", "1")
    monkeypatch.setattr(config, "DEPLOYED", True)
    auth._fails.clear()
    leaderboard.invalidate()
    yield root
    auth._fails.clear()
    leaderboard.invalidate()


def _app():
    from eklavya.webapp import create_app

    return create_app()


def _make_user(email, password="passwordlong1"):
    from eklavya import auth

    return auth.create_user(email, password)


def _seed(uid, *, pillar="FastAPI", axis="debugging", correct=3, wrong=0, ai_off=True):
    """Bind `uid`'s home and record some graded attempts into THAT user's own db, then
    restore the previous binding — mirroring how the aggregator reads each tenant."""
    from eklavya import config
    from eklavya.db import init_db
    from eklavya import tools

    token = config._current_home.set(config.user_home(uid))
    try:
        init_db()
        for _ in range(correct):
            tools.record_attempt(pillar, axis, "a concept", 2, True, 1.0, ai_off=ai_off)
        for _ in range(wrong):
            tools.record_attempt(pillar, axis, "a concept", 2, False, 1.0, ai_off=ai_off)
    finally:
        config._current_home.reset(token)


# --- migration: additive + existing data intact -----------------------------

def test_migration_is_additive_and_preserves_existing_rows(mu):
    """Creating accounts BEFORE the leaderboard columns are read, then reading them, must
    leave every account's email/status untouched and default the new columns to opted-out."""
    from eklavya import auth

    uid = auth.create_user("keep@example.com", "passwordlong1")
    before = auth.get_user(uid)

    prof = auth.leaderboard_profile(uid)
    assert prof == {"opted_in": False, "handle": None, "joined_at": None}

    # the account's own data is unchanged by the migration / profile read
    after = auth.get_user(uid)
    assert after == before
    # the new columns exist and defaulted correctly
    conn = auth._connect()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        row = conn.execute("SELECT lb_opted_in, lb_handle, lb_joined_at FROM users "
                           "WHERE id=?", (uid,)).fetchone()
    finally:
        conn.close()
    assert {"lb_opted_in", "lb_handle", "lb_joined_at"} <= cols
    assert row["lb_opted_in"] == 0 and row["lb_handle"] is None and row["lb_joined_at"] is None


# --- opt-in / opt-out flips visibility --------------------------------------

def test_opt_in_makes_user_appear_and_opt_out_removes(mu):
    from eklavya import auth, leaderboard

    uid = _make_user("player@example.com")
    _seed(uid)

    # absent before opting in
    assert leaderboard.build(me_uid=uid)["total"] == 0

    auth.set_leaderboard(uid, True, "Archer")
    leaderboard.invalidate()
    board = leaderboard.build(me_uid=uid)
    assert board["total"] == 1
    assert board["rows"][0]["handle"] == "Archer"
    assert board["me"] == {"opted_in": True, "handle": "Archer", "rank": 1}

    auth.set_leaderboard(uid, False)
    leaderboard.invalidate()
    board = leaderboard.build(me_uid=uid)
    assert board["total"] == 0
    assert board["me"]["opted_in"] is False


def test_non_opted_in_user_never_appears(mu):
    from eklavya import auth, leaderboard

    a = _make_user("a@example.com"); _seed(a)
    b = _make_user("b@example.com"); _seed(b)
    auth.set_leaderboard(a, True, "Alpha")   # only A opts in
    leaderboard.invalidate()

    board = leaderboard.build(me_uid=b)
    assert board["total"] == 1
    assert [r["handle"] for r in board["rows"]] == ["Alpha"]
    assert board["me"] == {"opted_in": False, "handle": None, "rank": None}


# --- handle uniqueness (case-insensitive) -----------------------------------

def test_handle_uniqueness_is_case_insensitive(mu):
    from eklavya import auth

    a = _make_user("a@example.com")
    b = _make_user("b@example.com")
    auth.set_leaderboard(a, True, "Hero")
    assert auth.handle_taken("hero", except_uid=b) is True
    assert auth.handle_taken("HERO", except_uid=b) is True
    with pytest.raises(ValueError):
        auth.set_leaderboard(b, True, "HERO")
    # A can re-case its OWN handle without being blocked by its own row
    auth.set_leaderboard(a, True, "HeRo")
    assert auth.leaderboard_profile(a)["handle"] == "HeRo"


def test_opt_out_preserves_handle_for_reuse(mu):
    from eklavya import auth

    a = _make_user("a@example.com")
    auth.set_leaderboard(a, True, "Keeper")
    joined = auth.leaderboard_profile(a)["joined_at"]
    auth.set_leaderboard(a, False)
    # handle preserved; nobody else can grab it while opted out
    b = _make_user("b@example.com")
    assert auth.handle_taken("keeper", except_uid=b) is True
    # re-opting in keeps the ORIGINAL join time
    auth.set_leaderboard(a, True, "Keeper")
    assert auth.leaderboard_profile(a)["joined_at"] == joined


# --- Eklavya Score determinism ----------------------------------------------

def test_eklavya_score_is_deterministic_for_fixed_inputs(mu):
    from eklavya import leaderboard

    args = dict(unassisted=1400, mastery_pct=50, xp=5000, streak=20,
                ach_unlocked=4, ach_total=9)
    s1 = leaderboard.eklavya_score(**args)
    s2 = leaderboard.eklavya_score(**args)
    assert s1 == s2 and isinstance(s1, int)

    # hand-computed against the documented weighting/normalisation
    u = min((1400 - 800) / 12, 1000)          # 50.0
    m = 50 / 100 * 1000                         # 500
    xp = min(5000, 20000) / 20000 * 1000        # 250
    st = min(20, 100) / 100 * 1000              # 200
    a = 4 / 9 * 1000                            # 444.4
    expect = round(0.40 * u + 0.20 * m + 0.20 * xp + 0.10 * st + 0.10 * a)
    assert s1 == expect

    # floor and cap behave
    assert leaderboard.eklavya_score(800, 0, 0, 0, 0, 9) == 0
    assert leaderboard.eklavya_score(99999, 100, 10 ** 9, 10 ** 9, 9, 9) == 1000


# --- sorting each column ----------------------------------------------------

def test_every_column_sorts(mu):
    from eklavya import auth, leaderboard

    # three users with clearly different metrics
    low = _make_user("low@example.com"); _seed(low, correct=1)
    mid = _make_user("mid@example.com"); _seed(mid, correct=5)
    high = _make_user("high@example.com"); _seed(high, correct=12)
    for uid, h in [(low, "Low"), (mid, "Mid"), (high, "High")]:
        auth.set_leaderboard(uid, True, h)
    leaderboard.invalidate()

    for col in ("score", "xp", "solved", "unassisted", "level", "streak",
                "achievements", "mastery"):
        leaderboard.invalidate()
        desc = leaderboard.build(sort=col, direction="desc")["rows"]
        vals_desc = [r[leaderboard.SORT_KEYS[col]] for r in desc]
        assert vals_desc == sorted(vals_desc, reverse=True), f"{col} desc"
        leaderboard.invalidate()
        asc = leaderboard.build(sort=col, direction="asc")["rows"]
        vals_asc = [r[leaderboard.SORT_KEYS[col]] for r in asc]
        assert vals_asc == sorted(vals_asc), f"{col} asc"

    # handle sorts alphabetically
    leaderboard.invalidate()
    handles = [r["handle"] for r in leaderboard.build(sort="handle", direction="asc")["rows"]]
    assert handles == sorted(handles, key=str.lower)


# --- tenant isolation: bind/restore -----------------------------------------

def test_two_user_aggregation_binds_and_restores_homes(mu):
    from eklavya import auth, config, leaderboard

    a = _make_user("a@example.com"); _seed(a, correct=3)
    b = _make_user("b@example.com"); _seed(b, correct=7)
    auth.set_leaderboard(a, True, "Aaa")
    auth.set_leaderboard(b, True, "Bbb")
    leaderboard.invalidate()

    # bind a specific home, aggregate, then assert the binding is untouched afterwards
    token = config._current_home.set(config.user_home(a))
    try:
        board = leaderboard.build(me_uid=a)
        assert board["total"] == 2
        # the caller's binding was restored after aggregating BOTH tenants
        assert config._current_home.get() == config.user_home(a)
    finally:
        config._current_home.reset(token)

    # each user's numbers are distinct (proves no cross-tenant bleed)
    by_handle = {r["handle"]: r for r in board["rows"]}
    assert by_handle["Bbb"]["solved"] == 7
    assert by_handle["Aaa"]["solved"] == 3


# --- no route leaks email / real name ---------------------------------------

_ALLOWED_ROW_KEYS = {
    "handle", "level", "xp", "streak", "solved", "achievements",
    "mastery_pct", "mastered", "total_groves", "unassisted", "score",
}


def test_builder_rows_carry_only_handle_and_numeric_fields(mu):
    from eklavya import auth, leaderboard

    uid = _make_user("secret.person@example.com"); _seed(uid)
    auth.set_leaderboard(uid, True, "Ghost")
    leaderboard.invalidate()

    board = leaderboard.build(me_uid=uid)
    row = board["rows"][0]
    assert set(row.keys()) <= _ALLOWED_ROW_KEYS
    assert "email" not in row and "_uid" not in row and "id" not in row
    # the raw email/uid appears nowhere in the serialised payload
    import json
    blob = json.dumps(board)
    assert "secret.person@example.com" not in blob
    assert uid not in blob


def test_api_get_leaderboard_never_leaks_email(mu):
    from eklavya import auth, leaderboard

    uid = _make_user("leaky@example.com"); _seed(uid)
    auth.set_leaderboard(uid, True, "Visible")
    leaderboard.invalidate()

    c = TestClient(_app(), follow_redirects=False)
    c.post("/login", data={"email": "leaky@example.com", "password": "passwordlong1"})
    r = c.get("/api/leaderboard")
    assert r.status_code == 200
    body = r.text
    assert "leaky@example.com" not in body and uid not in body
    data = r.json()
    assert data["rows"][0]["handle"] == "Visible"
    assert set(data["rows"][0].keys()) <= _ALLOWED_ROW_KEYS


# --- API: opt-in / opt-out routes -------------------------------------------

def test_api_opt_in_validates_and_persists(mu):
    from eklavya import auth

    uid = _make_user("api@example.com"); _seed(uid)
    c = TestClient(_app(), follow_redirects=False)
    c.post("/login", data={"email": "api@example.com", "password": "passwordlong1"})

    # too short / bad charset are rejected with a friendly 400
    assert c.post("/api/leaderboard/opt-in", json={"handle": "ab"}).status_code == 400
    assert c.post("/api/leaderboard/opt-in", json={"handle": "bad handle!"}).status_code == 400

    r = c.post("/api/leaderboard/opt-in", json={"handle": "  Valid_One  "})
    assert r.status_code == 200
    # trimmed + persisted + opted in
    assert auth.leaderboard_profile(uid) == {**auth.leaderboard_profile(uid),
                                             "opted_in": True, "handle": "Valid_One"}
    board = r.json()
    assert board["me"]["handle"] == "Valid_One" and board["me"]["opted_in"] is True

    # opt-out
    r2 = c.post("/api/leaderboard/opt-out")
    assert r2.status_code == 200 and r2.json()["me"]["opted_in"] is False


def test_api_opt_in_rejects_taken_handle(mu):
    from eklavya import auth

    other = _make_user("other@example.com")
    auth.set_leaderboard(other, True, "Taken")

    _make_user("me@example.com")
    c = TestClient(_app(), follow_redirects=False)
    c.post("/login", data={"email": "me@example.com", "password": "passwordlong1"})
    r = c.post("/api/leaderboard/opt-in", json={"handle": "taken"})  # case-insensitive clash
    assert r.status_code == 409


def test_leaderboard_routes_require_auth(mu):
    c = TestClient(_app(), follow_redirects=False)
    assert c.get("/api/leaderboard").status_code == 401
    assert c.post("/api/leaderboard/opt-in", json={"handle": "Nope"}).status_code == 401
    assert c.post("/api/leaderboard/opt-out").status_code == 401
