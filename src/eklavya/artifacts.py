"""Canvas artifacts — the durable things the guru writes and the learner keeps.

A lesson, a code file, a framed HTML page, or an interactive visual is an *artifact*:
it renders in the Canvas tab of the arena and lives on in the Scriptorium (the library).
Storage mirrors the rest of Ekalavya's split — the prose/render lives in `content`, the
numbers/metadata in columns. Per-user: `connect()` resolves the current user's db via the
contextvar, so each learner keeps their own collection with no path threading.

Plain functions with clear CRUD semantics — unit-testable without any LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .db import connect

# The artifact kinds the Canvas can render. Anything else is coerced to 'markdown'.
KINDS = ("markdown", "code", "html", "viz")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_kind(kind: str) -> str:
    kind = (kind or "").strip().lower()
    return kind if kind in KINDS else "markdown"


def _row(r) -> dict:
    keys = r.keys()
    return {
        "id": r["id"],
        "title": r["title"],
        "kind": r["kind"],
        "content": r["content"],
        "pinned": bool(r["pinned"]),
        "thread_id": r["thread_id"] if "thread_id" in keys else None,
        "pillar": r["pillar"] if "pillar" in keys else None,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def create(title: str, kind: str = "markdown", content: str = "",
           thread_id: str | None = None, pillar: str | None = None) -> dict:
    """Create a new artifact and return it (with its assigned id).

    `thread_id` links it to the chat that made it (defaults to the chat in flight, so the
    guru's save_artifact calls auto-associate); `pillar` tags it for the pillar-grouped
    library. Both optional — an ad-hoc artifact just has them NULL."""
    from . import config

    title = (title or "Untitled").strip() or "Untitled"
    thread_id = thread_id or config.current_thread()
    pillar = (pillar or "").strip() or None
    now = _now()
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO artifacts(title, kind, content, thread_id, pillar, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (title, _norm_kind(kind), content or "", thread_id, pillar, now, now),
        )
        conn.commit()
        return get(cur.lastrowid)  # type: ignore[arg-type]
    finally:
        conn.close()


def get(artifact_id: int) -> dict | None:
    """Return one artifact by id, or None if it doesn't exist."""
    conn = connect()
    try:
        r = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        return _row(r) if r else None
    finally:
        conn.close()


def list_artifacts(kind: str | None = None, query: str | None = None,
                   pillar: str | None = None) -> list[dict]:
    """List artifacts newest-first, pinned ones first. Optional filter by kind, pillar,
    and/or a case-insensitive search over title + content."""
    sql = "SELECT * FROM artifacts"
    where, params = [], []
    if kind:
        where.append("kind = ?")
        params.append(_norm_kind(kind))
    if pillar:
        where.append("pillar = ?")
        params.append(pillar)
    if query:
        where.append("(title LIKE ? OR content LIKE ?)")
        like = f"%{query.strip()}%"
        params += [like, like]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY pinned DESC, updated_at DESC, id DESC"
    conn = connect()
    try:
        return [_row(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def update(artifact_id: int, *, title: str | None = None, kind: str | None = None,
           content: str | None = None, pinned: bool | None = None) -> dict | None:
    """Patch the given fields on an artifact. Only the fields passed are changed.
    Returns the updated artifact, or None if it doesn't exist."""
    sets, params = [], []
    if title is not None:
        sets.append("title = ?")
        params.append(title.strip() or "Untitled")
    if kind is not None:
        sets.append("kind = ?")
        params.append(_norm_kind(kind))
    if content is not None:
        sets.append("content = ?")
        params.append(content)
    if pinned is not None:
        sets.append("pinned = ?")
        params.append(int(bool(pinned)))
    if not sets:
        return get(artifact_id)
    sets.append("updated_at = ?")
    params.append(_now())
    params.append(artifact_id)
    conn = connect()
    try:
        cur = conn.execute(f"UPDATE artifacts SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        if cur.rowcount == 0:
            return None
    finally:
        conn.close()
    return get(artifact_id)


def pin(artifact_id: int, pinned: bool = True) -> dict | None:
    """Pin or unpin an artifact (pinned artifacts sort to the top of the library)."""
    return update(artifact_id, pinned=pinned)


def delete(artifact_id: int) -> bool:
    """Delete an artifact. Returns True if a row was removed."""
    conn = connect()
    try:
        cur = conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
