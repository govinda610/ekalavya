"""The opt-in, privacy-safe leaderboard aggregator (deployed multi-user).

The board only means anything with several accounts, so it's a DEPLOYED-mode feature: it
ranks the users who have chosen a public handle and opted in (``auth.set_leaderboard``).
Everything here is READ-ONLY. For each opted-in user we bind that user's home into the
per-request contextvar (``config.set_current_home``), pull the numbers from their OWN
database via the existing report/progress/effectiveness helpers — the single source of
truth, no new metric store — then RESTORE the previous binding in a ``finally`` so tenants
never cross. A board row carries ONLY the handle + numeric columns; email / real name / uid
never leave this module.

The **Eklavya Score** is a transparent composite (see docs/design/LEADERBOARD_SPEC.md §
"Eklavya Score"). Every normalisation constant lives in ``_NORM`` below so the whole
weighting is retunable in one place once real user data exists.
"""

from __future__ import annotations

import time

from . import auth, config, dashboard, effectiveness, progress, report

# --- Eklavya Score normalisation (ONE place, easy to retune) ----------------
# Each component maps to a 0–1000 sub-score, then the weights (which sum to 1.0) combine
# them into a final 0–1000 integer. The comments trace each constant to the spec.
_NORM = {
    # 40% Unassisted skill — the AI-off Elo rating (the honest core). The app's Elo sits on
    # ~800 (floor) … ~1500 (strong) in practice; the spec's `(rating - 800) / 12` maps an
    # 800 floor → 0 and a (currently unreachable) ~12800 → capped 1000, deliberately leaving
    # head-room so the column keeps discriminating as real ratings climb. Retune the divisor
    # down once the real rating spread is known.
    "unassisted_floor": 800.0,
    "unassisted_divisor": 12.0,
    # 20% XP — linear to a cap. 20_000 XP ≈ level 200; a generous ceiling so early users
    # aren't all pinned at 1000. Retune from the real XP spread.
    "xp_cap": 20_000.0,
    # 10% Streak — linear to 100 days.
    "streak_cap": 100.0,
    # weights (must sum to 1.0)
    "w_unassisted": 0.40,
    "w_mastery": 0.20,
    "w_xp": 0.20,
    "w_streak": 0.10,
    "w_achievements": 0.10,
}

_CACHE_TTL = 45.0  # seconds — a page load doesn't re-scan every user's db each time.
_cache: dict[tuple, tuple[float, dict]] = {}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def eklavya_score(unassisted: float, mastery_pct: float, xp: int,
                  streak: int, ach_unlocked: int, ach_total: int) -> int:
    """The transparent composite → a 0–1000 integer. Deterministic for fixed inputs.

    - unassisted: the AI-off Elo rating (≈800 floor)
    - mastery_pct: mastered groves / total groves, as a percent 0–100
    - xp / streak: raw counters
    - ach_unlocked / ach_total: achievements unlocked out of the catalogue size
    """
    n = _NORM
    u = _clamp((unassisted - n["unassisted_floor"]) / n["unassisted_divisor"], 0, 1000)
    m = _clamp(mastery_pct / 100.0 * 1000, 0, 1000)
    xp_sub = _clamp(min(xp, n["xp_cap"]) / n["xp_cap"] * 1000, 0, 1000)
    s = _clamp(min(streak, n["streak_cap"]) / n["streak_cap"] * 1000, 0, 1000)
    a = _clamp((ach_unlocked / ach_total * 1000) if ach_total else 0, 0, 1000)
    total = (n["w_unassisted"] * u + n["w_mastery"] * m + n["w_xp"] * xp_sub
             + n["w_streak"] * s + n["w_achievements"] * a)
    return round(total)


# A human-readable statement of the weighting, surfaced verbatim in the UI tooltip so the
# score is never a black box.
WEIGHTING_TEXT = ("40% unassisted skill · 20% mastery · 20% XP · 10% streak · "
                  "10% achievements")

# The sortable columns and which row key each maps to (all numeric except the handle).
SORT_KEYS = {
    "score": "score", "level": "level", "xp": "xp", "streak": "streak",
    "solved": "solved", "achievements": "achievements", "mastery": "mastery_pct",
    "unassisted": "unassisted", "handle": "handle",
}


def _metrics_for_current_user() -> dict:
    """Pull one opted-in user's public metrics from THEIR bound database (read-only).

    Called with that user's home already bound. Returns the numeric columns only — never any
    identifying field. "Questions solved" = the count of CORRECT attempts (the meaningful,
    non-inflatable signal: wrong tries and abandoned drills don't count).
    """
    from .db import connect

    stats = progress.stats()

    # mastered vs total groves, from the forest map's grove statuses ('blossoming' = mastered)
    fm = report.forest_map()
    groves = fm.get("groves") or []
    total_groves = len(groves)
    mastered = sum(1 for g in groves if g.get("status") == "blossoming")
    mastery_pct = round(100 * mastered / total_groves) if total_groves else 0

    # strong-skill count (for the achievement predicate) from the mastery grid
    strong = 0
    for cells in report.grid().get("pillars", {}).values():
        for cell in cells.values():
            if cell["level"] == "strong":
                strong += 1

    # unassisted skill = the app's AI-off Elo (mean pillar rating); floor when no attempts yet
    overall = effectiveness.elo().get("overall_rating")
    unassisted = float(overall) if overall is not None else _NORM["unassisted_floor"]

    conn = connect()
    try:
        solved = conn.execute(
            "SELECT COUNT(*) AS c FROM attempts WHERE correct = 1"
        ).fetchone()["c"]
        sessions = conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]
    finally:
        conn.close()

    ach_unlocked = len(dashboard.earned_achievements(stats, strong, sessions))
    score = eklavya_score(unassisted, mastery_pct, stats["xp"], stats["streak"],
                          ach_unlocked, dashboard.ACHIEVEMENTS_TOTAL)
    return {
        "level": stats["level"],
        "xp": stats["xp"],
        "streak": stats["streak"],
        "solved": int(solved),
        "achievements": ach_unlocked,
        "mastery_pct": mastery_pct,
        "mastered": mastered,
        "total_groves": total_groves,
        "unassisted": round(unassisted),
        "score": score,
    }


def _collect_rows() -> list[dict]:
    """One row per opted-in user (handle + numeric columns). Binds each user's home read-only
    and RESTORES the previous binding in a finally, so aggregating the board never leaks the
    caller's tenant into another user's context (or vice versa)."""
    rows: list[dict] = []
    for u in auth.opted_in_users():
        token = config._current_home.set(config.user_home(u["id"]))
        try:
            m = _metrics_for_current_user()
        except Exception:
            # a single unreadable/half-initialised user db must not sink the whole board
            continue
        finally:
            config._current_home.reset(token)
        rows.append({"_uid": u["id"], "handle": u["handle"], **m})
    return rows


def _sorted(rows: list[dict], sort: str, direction: str) -> list[dict]:
    """Sort by the requested column. The PRIMARY key follows `direction` (asc/desc); the
    TIE-BREAKS are FIXED regardless of direction — Eklavya Score descending, then handle
    ascending (case-insensitive) — so equal rows always read in the same deterministic order
    (spec: "ties broken by Eklavya Score, then handle"). `handle` is the only alpha column;
    every other column is numeric.
    """
    key = SORT_KEYS.get(sort, "score")
    asc = direction == "asc"

    def sort_key(r: dict):
        if key == "handle":
            primary = _alpha(r["handle"], asc)
        else:
            primary = r[key] if asc else -r[key]
        # tie-breaks are always the same orientation: score desc, then handle A→Z
        return (primary, -r["score"], _alpha(r["handle"], ascending=True))

    rows.sort(key=sort_key)
    return rows


def _alpha(handle: str, ascending: bool = True):
    """A comparable key for a handle (case-insensitive). When `ascending`, A→Z; otherwise the
    per-char ords are negated so a plain ascending sort yields Z→A — used so the handle column
    itself can flip direction while the tie-break stays A→Z."""
    h = handle.lower()
    return h if ascending else tuple(-ord(c) for c in h)


def build(sort: str = "score", direction: str = "desc", me_uid: str | None = None) -> dict:
    """The full leaderboard payload.

    Returns ``{me: {opted_in, handle, rank}, rows: [...], total}``. Rows carry ONLY the handle
    and the numeric columns — never email / real name / uid (the internal ``_uid`` used for the
    'me' match is stripped before returning). Cached ~45s per (sort, direction).
    """
    sort = sort if sort in SORT_KEYS else "score"
    direction = "asc" if direction == "asc" else "desc"
    cache_key = (sort, direction)
    now = time.monotonic()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < _CACHE_TTL:
        rows = hit[1]["rows"]
        row_uids = hit[1]["uids"]
    else:
        collected = _sorted(_collect_rows(), sort, direction)
        row_uids = [r["_uid"] for r in collected]
        rows = [{k: v for k, v in r.items() if k != "_uid"} for r in collected]
        _cache[cache_key] = (now, {"rows": rows, "uids": row_uids})

    total = len(rows)
    me = {"opted_in": False, "handle": None, "rank": None}
    if me_uid is not None:
        prof = auth.leaderboard_profile(me_uid)
        me["opted_in"] = prof["opted_in"]
        me["handle"] = prof["handle"]
        if prof["opted_in"] and me_uid in row_uids:
            me["rank"] = row_uids.index(me_uid) + 1
    return {"me": me, "rows": rows, "total": total}


def invalidate() -> None:
    """Drop the cache (called after an opt-in/opt-out so the board reflects it immediately)."""
    _cache.clear()
