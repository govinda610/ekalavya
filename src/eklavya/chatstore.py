"""Persistent chat storage — so conversations survive restarts and get a history.

Two parts, mirroring the rest of Ekalavya's storage split:
  - the LangGraph **checkpointer** (SqliteSaver on ~/.eklavya/checkpoints.sqlite) holds
    the durable, resumable conversation state per thread_id — this is what lets a chat
    be *continued* with full context after a restart;
  - a small **chats** table in eklavya.db holds the sidebar metadata (title, mode,
    timestamps) so we can list, order, rename, and auto-name past chats.

Reconstructing a transcript for display reads the messages back out of the checkpointer
and keeps only the human + assistant turns (tool calls belong in the thinking trace).
"""

from __future__ import annotations

import sqlite3

from . import config
from .db import connect

_saver = None


def get_checkpointer():
    """A process-wide SqliteSaver so conversations persist across restarts."""
    global _saver
    if _saver is None:
        from langgraph.checkpoint.sqlite import SqliteSaver

        config.ensure_home()
        conn = sqlite3.connect(str(config.EKLAVYA_HOME / "checkpoints.sqlite"),
                               check_same_thread=False)
        _saver = SqliteSaver(conn)
        _saver.setup()
    return _saver


# --- chats index (sidebar metadata) ----------------------------------------

def touch_chat(thread_id: str, mode: str | None = None, title: str | None = None) -> None:
    """Create the chat row if new, and bump its updated_at. Optionally set mode/title."""
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO chats(thread_id, mode, title) VALUES(?, ?, ?) "
            "ON CONFLICT(thread_id) DO UPDATE SET updated_at = datetime('now'), "
            "mode = COALESCE(excluded.mode, chats.mode), "
            "title = COALESCE(chats.title, excluded.title)",
            (thread_id, mode, title),
        )
        conn.commit()
    finally:
        conn.close()


def list_chats() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT thread_id, title, mode, created_at, updated_at "
            "FROM chats ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def rename_chat(thread_id: str, title: str) -> None:
    conn = connect()
    try:
        conn.execute("UPDATE chats SET title = ? WHERE thread_id = ?", (title.strip(), thread_id))
        conn.commit()
    finally:
        conn.close()


def get_title(thread_id: str) -> str | None:
    conn = connect()
    try:
        row = conn.execute("SELECT title FROM chats WHERE thread_id = ?", (thread_id,)).fetchone()
    finally:
        conn.close()
    return row["title"] if row and row["title"] else None


def get_chat(thread_id: str) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT thread_id, title, mode, created_at, updated_at FROM chats WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


# --- transcript reconstruction (for display / continue) --------------------

def _text(message) -> str:
    """Best-effort plain text from a LangChain message (content may be str or blocks)."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content or "")


_reader = None


def _reader_agent():
    """A minimal deep agent sharing the persistent checkpointer, used only to read
    conversation state back out (deepagents reconstructs messages via get_state, not
    from the raw checkpoint tuple). Cached so we don't rebuild it per call."""
    global _reader
    if _reader is None:
        from .agent import build_agent

        _reader = build_agent("reader", [], checkpointer=get_checkpointer())
    return _reader


def _messages(thread_id: str) -> list:
    try:
        state = _reader_agent().get_state({"configurable": {"thread_id": thread_id}})
        return state.values.get("messages", []) or []
    except Exception:
        return []


def transcript(thread_id: str) -> list[dict]:
    """The human + assistant turns of a chat, in order, for display.

    Tool calls / tool results are omitted here (they belong in the thinking trace, #22).
    """
    out = []
    for m in _messages(thread_id):
        role = getattr(m, "type", None)  # 'human' | 'ai' | 'tool' | 'system'
        if role not in ("human", "ai"):
            continue
        text = _text(m).strip()
        if text:
            out.append({"role": "you" if role == "human" else "ai", "text": text})
    return out


def auto_title(thread_id: str, limit: int = 48, skip: set | None = None) -> str | None:
    """A short title from the first substantive human message (heuristic; user can rename).

    `skip` is a set of exact message texts to ignore — pass the boilerplate kickoff
    messages so a chat is titled by the learner's first real message, not the greeting.
    """
    skip = skip or set()
    for m in _messages(thread_id):
        if getattr(m, "type", None) != "human":
            continue
        raw = _text(m).strip()
        if not raw or raw in skip:
            continue
        first = " ".join(raw.splitlines()[0].split())
        if first:
            return first[:limit] + ("…" if len(first) > limit else "")
    return None
