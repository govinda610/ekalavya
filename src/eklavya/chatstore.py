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

# Per-user savers, keyed by the resolved checkpoints path (one SqliteSaver per user file).
# In single-user mode there's exactly one key, so behaviour is unchanged.
_savers: dict[str, object] = {}


def get_checkpointer():
    """The SqliteSaver for the CURRENT user, cached per checkpoints file.

    Reads the checkpoints path from ``config.paths()`` (contextvar-aware) so each user
    gets their own durable conversation store; single-user resolves to the one file.
    """
    path = config.paths().checkpoints
    key = str(path)
    saver = _savers.get(key)
    if saver is None:
        from langgraph.checkpoint.sqlite import SqliteSaver

        config.ensure_home()
        conn = sqlite3.connect(key, check_same_thread=False)
        saver = SqliteSaver(conn)
        saver.setup()
        _savers[key] = saver
    return saver


# --- chats index (sidebar metadata) ----------------------------------------

def current_user_id() -> str | None:
    """The id owning the current context, or None when ownership isn't enforced.

    A local self-host has a single account, so ``chats.user_id`` stays NULL and there is no
    cross-user ownership to enforce. A deployed install resolves the id from the per-user
    home the auth middleware bound (``…/users/<uid>``) so threads carry their owner.
    """
    if not config.DEPLOYED:
        return None
    return config.paths().home.name  # user home is …/users/<uid>


def touch_chat(thread_id: str, mode: str | None = None, title: str | None = None) -> None:
    """Create the chat row if new, and bump its updated_at. Optionally set mode/title.

    Stamps the current user's id on first touch so thread ownership can be enforced
    (no-op in single-user mode, where user_id stays NULL)."""
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO chats(thread_id, mode, title, user_id) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(thread_id) DO UPDATE SET updated_at = datetime('now'), "
            "mode = COALESCE(excluded.mode, chats.mode), "
            "title = COALESCE(chats.title, excluded.title)",
            (thread_id, mode, title, current_user_id()),
        )
        conn.commit()
    finally:
        conn.close()


def owns_thread(thread_id: str) -> bool:
    """True if the current user may serve/resume/rename this thread.

    Local self-host (user_id NULL, one account): always True. Deployed: True only
    when the row's owner matches the current user, or the thread has no row yet (a
    brand-new thread the caller is about to create). A thread owned by someone else
    returns False → callers should 404 (don't confirm existence)."""
    if not config.DEPLOYED:
        return True
    conn = connect()
    try:
        row = conn.execute(
            "SELECT user_id FROM chats WHERE thread_id = ?", (thread_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return True  # not created yet — the caller will own it on first touch
    return row["user_id"] == current_user_id()


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


def delete_chat(thread_id: str) -> bool:
    """Delete a chat's sidebar row AND its durable checkpointer state.

    Removes the row from the ``chats`` index in eklavya.db, then purges that thread's
    rows from the LangGraph checkpointer (the ``checkpoints`` and ``writes`` tables in
    checkpoints.sqlite) so no resumable state lingers. Returns True if a chat row was
    deleted. Operates only in the current context's dbs (per-user safe); the checkpoint
    purge is idempotent and skips tables that don't exist yet (a never-used checkpointer).
    """
    conn = connect()
    try:
        cur = conn.execute("DELETE FROM chats WHERE thread_id = ?", (thread_id,))
        conn.commit()
        deleted = cur.rowcount > 0
    finally:
        conn.close()

    cp = connect(config.paths().checkpoints)
    try:
        tables = {r["name"] for r in cp.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("checkpoints", "writes"):
            if table in tables:
                cp.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
        cp.commit()
    finally:
        cp.close()

    return deleted


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


# Per-user reader agents, keyed by the checkpoints file (each embeds that user's saver).
_readers: dict[str, object] = {}


def _reader_agent():
    """A minimal deep agent sharing the CURRENT user's persistent checkpointer, used only
    to read conversation state back out (deepagents reconstructs messages via get_state,
    not from the raw checkpoint tuple). Cached per user so we don't rebuild it per call."""
    key = str(config.paths().checkpoints)
    reader = _readers.get(key)
    if reader is None:
        from .agent import build_agent

        reader = build_agent("reader", [], checkpointer=get_checkpointer())
        _readers[key] = reader
    return reader


def _messages(thread_id: str) -> list:
    try:
        state = _reader_agent().get_state({"configurable": {"thread_id": thread_id}})
        return state.values.get("messages", []) or []
    except Exception:
        return []


import re as _re

# The private "[session context — …]" briefing the app prepends to each user turn (#59) is
# for the AGENT only — strip it from anything the learner sees (transcript, chat title).
_CTX_RE = _re.compile(r"^\[session context —[^\]]*\]\s*\n+")


def _strip_ctx(text: str) -> str:
    return _CTX_RE.sub("", text or "", count=1)


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
        if role == "human":
            text = _strip_ctx(text).strip()   # hide the private session-context briefing
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
        raw = _strip_ctx(_text(m)).strip()   # title from the real message, not the ctx briefing
        if not raw or raw in skip:
            continue
        first = " ".join(raw.splitlines()[0].split())
        if first:
            return first[:limit] + ("…" if len(first) > limit else "")
    return None
