"""The interactive conversation loop between the learner and the agent.

`run_turn` is a single request/response (easy to unit-test). `chat_loop` is the
human-facing REPL built on top of it.
"""

from __future__ import annotations

import uuid

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .commands import EXIT, handle_slash


def new_thread() -> dict:
    """A fresh conversation id, so history persists across turns via the checkpointer."""
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def run_turn(agent, config: dict, user_text: str) -> str:
    """Send one user message, return the agent's final reply text (with a self-check
    correction appended if a second model flags a technical error)."""
    from .verify import selfcheck

    result = agent.invoke({"messages": [{"role": "user", "content": user_text}]}, config=config)
    reply = result["messages"][-1].text
    note = selfcheck(reply)
    return reply + note if note else reply


def _show(console: Console, text: str) -> None:
    console.print(Panel(Markdown(text), border_style="cyan", title="[bold cyan]Ekalavya[/]",
                        padding=(1, 2)))


def _autoname(thread_id: str, kickoff: str | None) -> None:
    """Name a chat from the learner's first real message (skipping the kickoff)."""
    try:
        from .chatstore import auto_title, get_title, rename_chat

        if get_title(thread_id) is None:
            title = auto_title(thread_id, skip={kickoff} if kickoff else None)
            if title:
                rename_chat(thread_id, title)
    except Exception:
        pass


def chat_loop(agent, kickoff: str | None, console: Console | None = None,
              config: dict | None = None, mode: str | None = None,
              replay: list | None = None) -> None:
    """Run the REPL. `kickoff` starts a NEW chat; pass `config` + `replay` to resume an
    existing one. `mode` registers the chat in the shared history (listable/resumable
    from both the terminal and the web)."""
    console = console or Console()
    config = config or new_thread()
    thread_id = config["configurable"]["thread_id"]
    if mode:
        from .chatstore import touch_chat

        touch_chat(thread_id, mode=mode)

    if replay:  # resuming — show the prior turns, don't re-run the kickoff
        for m in replay:
            if m["role"] == "you":
                console.print(f"[bold green]you ›[/] {m['text']}")
            else:
                _show(console, m["text"])
    elif kickoff:
        with console.status("[dim]thinking…[/]"):
            reply = run_turn(agent, config, kickoff)
        _show(console, reply)

    console.print("[dim](type your answer · /help for commands · /exit to leave)[/]\n")
    while True:
        try:
            user = console.input("[bold green]you ›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]session paused. your progress is saved.[/]")
            break
        if not user:
            continue
        slash = handle_slash(user)
        if slash is not None:
            if slash == EXIT:
                console.print("[dim]session paused. your progress is saved.[/]")
                break
            console.print(Panel(slash, border_style="magenta", title="[magenta]/[/]", padding=(0, 2)))
            continue
        with console.status("[dim]thinking…[/]"):
            reply = run_turn(agent, config, user)
        _show(console, reply)
        if mode:
            _autoname(thread_id, kickoff)
