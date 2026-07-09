"""The interactive conversation loop between the learner and the agent.

`run_turn` is a single request/response (easy to unit-test). `chat_loop` is the
human-facing REPL built on top of it.
"""

from __future__ import annotations

import uuid

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel


def new_thread() -> dict:
    """A fresh conversation id, so history persists across turns via the checkpointer."""
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


def run_turn(agent, config: dict, user_text: str) -> str:
    """Send one user message, return the agent's final reply text."""
    result = agent.invoke({"messages": [{"role": "user", "content": user_text}]}, config=config)
    return result["messages"][-1].text


def _show(console: Console, text: str) -> None:
    console.print(Panel(Markdown(text), border_style="cyan", title="[bold cyan]Ekalavya[/]",
                        padding=(1, 2)))


def chat_loop(agent, kickoff: str, console: Console | None = None) -> None:
    """Run the REPL. `kickoff` is the (hidden) first instruction that starts it."""
    console = console or Console()
    config = new_thread()

    with console.status("[dim]thinking…[/]"):
        reply = run_turn(agent, config, kickoff)
    _show(console, reply)

    console.print("[dim](type your answer · /exit to leave)[/]\n")
    while True:
        try:
            user = console.input("[bold green]you ›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]session paused. your progress is saved.[/]")
            break
        if user.lower() in ("/exit", "/quit"):
            console.print("[dim]session paused. your progress is saved.[/]")
            break
        if not user:
            continue
        with console.status("[dim]thinking…[/]"):
            reply = run_turn(agent, config, user)
        _show(console, reply)
