"""Streak, XP, and level — the visible-progress layer.

Small and honest: XP accrues per attempt, the streak counts consecutive active
days, and level is a simple function of XP. All persisted in the meta/rewards
tables so the dashboard and the agent can read the same numbers.
"""

from __future__ import annotations

from datetime import date, timedelta


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


def stats() -> dict:
    from .db import connect

    conn = connect()
    try:
        xp = int(_get(conn, "xp", "0"))
        streak = int(_get(conn, "streak", "0"))
    finally:
        conn.close()
    return {"xp": xp, "streak": streak, "level": level_for(xp)}


# --- sessions --------------------------------------------------------------


def start_session(minutes: int, mode: str = "guided") -> int:
    """Open a session row and remember it as current. Returns the session id."""
    from .db import connect

    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO sessions(planned_min, mode) VALUES(?, ?)", (minutes, mode)
        )
        sid = cur.lastrowid
        _set(conn, "current_session", sid)
        conn.commit()
    finally:
        conn.close()
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
