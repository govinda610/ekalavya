"""Streak, XP, and level — the visible-progress layer.

Small and honest: XP accrues per attempt, the streak counts consecutive active
days, and level is a simple function of XP. All persisted in the meta/rewards
tables so the dashboard and the agent can read the same numbers.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

# Anti-cheat: only a LARGE paste that makes up most of the submitted solution
# counts. Small/agent-provided pastes and dictation inserts are ignored — we bias
# hard toward false negatives (a missed cheat is far cheaper than a false accusation).
PASTE_MIN_CHARS = 240
PASTE_DOMINANCE = 0.6


def looks_pasted(code: str, biggest_paste: int) -> bool:
    """True only when a single big paste dominates a code-like submission."""
    code = (code or "").strip()
    if not code or biggest_paste < PASTE_MIN_CHARS:
        return False
    if biggest_paste < PASTE_DOMINANCE * len(code):
        return False
    return bool(re.search(r"\b(def|return|for|while|class|import)\b|[={}()]", code))


def _get(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _set(conn, key: str, value) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def level_for(xp: int) -> int:
    """A gentle curve: a new level every 100 XP."""
    return 1 + xp // 100


def award_xp(amount: int, label: str = "", cause: str = "") -> int:
    from .db import connect

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO rewards(kind, amount, label, cause) VALUES('xp', ?, ?, ?)",
            (amount, label, cause),
        )
        total = int(_get(conn, "xp", "0")) + amount
        _set(conn, "xp", total)
        conn.commit()
    finally:
        conn.close()
    return total


def penalise(reason: str = "", xp_loss: int = 50) -> dict:
    """Souls-like penalty: drop XP, break the streak, and leave the dropped souls
    on the ground (reclaimable). Returns what was lost."""
    from .db import connect

    conn = connect()
    try:
        xp = int(_get(conn, "xp", "0"))
        lost = min(xp, xp_loss)
        _set(conn, "xp", xp - lost)
        _set(conn, "streak", 0)
        _set(conn, "last_active", "")  # break the chain
        _set(conn, "penance", lost)    # souls waiting to be reclaimed
        conn.execute(
            "INSERT INTO rewards(kind, amount, label, cause) VALUES('penalty', ?, 'souls dropped', ?)",
            (-lost, reason),
        )
        conn.commit()
    finally:
        conn.close()
    return {"lost": lost}


def penance() -> int:
    """XP currently dropped and waiting to be reclaimed (0 if none)."""
    from .db import connect

    conn = connect()
    try:
        return int(_get(conn, "penance", "0"))
    finally:
        conn.close()


def reclaim() -> int:
    """Reclaim dropped souls by proving you'll do it yourself. Returns amount restored."""
    from .db import connect

    conn = connect()
    try:
        amount = int(_get(conn, "penance", "0"))
        if amount:
            _set(conn, "xp", int(_get(conn, "xp", "0")) + amount)
            _set(conn, "penance", 0)
            conn.execute(
                "INSERT INTO rewards(kind, amount, label, cause) "
                "VALUES('xp', ?, 'souls reclaimed', 'typed it yourself')",
                (amount,),
            )
            conn.commit()
    finally:
        conn.close()
    return amount


def touch_streak(today: str | None = None) -> int:
    """Register activity for `today`; extend the streak if yesterday was active."""
    from .db import connect

    today = today or date.today().isoformat()
    conn = connect()
    try:
        last = _get(conn, "last_active")
        streak = int(_get(conn, "streak", "0"))
        if last != today:
            yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
            streak = streak + 1 if last == yesterday else 1
            _set(conn, "streak", streak)
            _set(conn, "last_active", today)
            conn.commit()
    finally:
        conn.close()
    return streak


# A stated confidence (1 guessing / 2 pretty sure / 3 certain) → the learner's implied
# probability of being right. Used to score calibration ("the illusion of knowing").
_CONF_P = {1: 0.35, 2: 0.65, 3: 0.90}


def calibration(window: int = 50, subject: str | None = None) -> dict:
    """The calibration signal over the last `window` graded attempts — the product's
    headline "do you know what you know?" metric, which the rating math already reacts
    to but which was never surfaced on its own. Scoped to one `subject` when given (a
    learner may be well-calibrated in coding but overconfident in econometrics).

    Returns {n, brier, bias, confidently_wrong}:
      - brier: mean squared gap between stated confidence and being right (0 = perfect,
        lower is better);
      - bias: >0 overconfident, <0 underconfident, ~0 well-calibrated;
      - confidently_wrong: attempts marked 'certain' (3) yet wrong — the costliest,
        the pure illusion of knowing.
    n=0 (with null metrics) when there's no data yet.
    """
    from .db import connect

    conn = connect()
    try:
        if subject:
            rows = conn.execute(
                "SELECT confidence AS c, correct AS k FROM attempts "
                "WHERE confidence IS NOT NULL AND subject = ? ORDER BY id DESC LIMIT ?",
                (subject, int(window)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT confidence AS c, correct AS k FROM attempts "
                "WHERE confidence IS NOT NULL ORDER BY id DESC LIMIT ?", (int(window),)
            ).fetchall()
    finally:
        conn.close()
    pairs = [(r["c"], int(bool(r["k"]))) for r in rows if r["c"] in _CONF_P]
    if not pairs:
        return {"n": 0, "brier": None, "bias": None, "confidently_wrong": 0}
    n = len(pairs)
    brier = sum((_CONF_P[c] - k) ** 2 for c, k in pairs) / n
    bias = sum(_CONF_P[c] - k for c, k in pairs) / n
    confidently_wrong = sum(1 for c, k in pairs if c == 3 and k == 0)
    return {"n": n, "brier": round(brier, 3), "bias": round(bias, 3),
            "confidently_wrong": confidently_wrong}


def stats() -> dict:
    from .db import connect

    conn = connect()
    try:
        xp = int(_get(conn, "xp", "0"))
        streak = int(_get(conn, "streak", "0"))
        last = _get(conn, "last_active")
    finally:
        conn.close()
    # Report the streak LIVE: it's only alive if the last active day was today or yesterday
    # (you can still continue it today). After a longer gap it's already broken — even though
    # touch_streak only rewrites the stored value on the next activity. Don't show a stale streak.
    if streak and last:
        try:
            if (date.today() - date.fromisoformat(last)).days > 1:
                streak = 0
        except ValueError:
            pass
    return {"xp": xp, "streak": streak, "level": level_for(xp),
            "calibration": calibration()}


# --- sessions --------------------------------------------------------------

# A "sitting" stays open while the learner keeps interacting; a gap longer than this
# (minutes) means they left and came back → it counts as a new session.
IDLE_GAP_MIN = 45


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_ts(ts: str | None):
    """Parse a stored timestamp (naive `datetime('now')` OR aware ISO) as UTC-aware,
    so arithmetic against an aware `now` never raises."""
    from datetime import datetime, timezone

    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def start_session(minutes: int, mode: str = "guided") -> int:
    """Open a session row and remember it as current. Returns the session id.

    Also kicks off a throttled, background, offline-safe refresh of the interview-question
    bank toward the learner's targets (see `questions_refresh.maybe_autorefresh`). It never
    blocks this call or raises — a session always starts even if the refresh can't run.
    """
    from .db import connect

    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO sessions(planned_min, mode, last_active) VALUES(?, ?, ?)",
            (minutes, mode, _utcnow()),
        )
        sid = cur.lastrowid
        _set(conn, "current_session", sid)
        conn.commit()
    finally:
        conn.close()

    try:
        from .questions_refresh import maybe_autorefresh

        maybe_autorefresh()
    except Exception:
        pass  # a refresh hiccup must never stop a session from starting
    return sid


def current_session(conn) -> int | None:
    val = _get(conn, "current_session")
    return int(val) if val else None


def end_session() -> None:
    """Finalise the current session: stamp its end time and total XP."""
    from datetime import datetime, timezone

    from .db import connect

    conn = connect()
    try:
        sid = current_session(conn)
        if sid:
            xp = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS xp FROM rewards "
                "WHERE kind='xp' AND created_at >= (SELECT started_at FROM sessions WHERE id=?)",
                (sid,),
            ).fetchone()["xp"]
            conn.execute(
                "UPDATE sessions SET ended_at=?, xp=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), xp, sid),
            )
            _set(conn, "current_session", "")
            conn.commit()
    finally:
        conn.close()


def ensure_session(minutes: int, mode: str = "guided") -> int:
    """Return the current sitting, opening a new one only after an idle gap.

    The web app has no explicit start/stop, so a "session" is a contiguous burst of
    activity: if the current session was active within IDLE_GAP_MIN minutes we reuse it
    (and bump its activity); otherwise we finalise the stale one and open a fresh one.
    Idempotent to call on every turn.
    """
    from datetime import datetime, timedelta, timezone

    from .db import connect

    conn = connect()
    try:
        sid = current_session(conn)
        if sid:
            row = conn.execute(
                "SELECT last_active, started_at, ended_at FROM sessions WHERE id=?", (sid,)
            ).fetchone()
            last = _parse_ts(row["last_active"] if row else None) if row else None
            fresh = (
                row and not row["ended_at"] and last is not None
                and datetime.now(timezone.utc) - last <= timedelta(minutes=IDLE_GAP_MIN)
            )
            if fresh:
                conn.execute("UPDATE sessions SET last_active=? WHERE id=?", (_utcnow(), sid))
                conn.commit()
                return sid
            # stale → close it out so the gap is measurable next time
            if row and not row["ended_at"]:
                conn.execute(
                    "UPDATE sessions SET ended_at=? WHERE id=?",
                    (row["last_active"] or row["started_at"], sid),
                )
                conn.commit()
    finally:
        conn.close()
    return start_session(minutes, mode)
