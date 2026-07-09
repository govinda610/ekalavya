"""The immersive terminal UI — a chat with the tutor plus a built-in code editor.

Kept simple: a scrolling conversation, an input line, and a togglable Python
editor so you write code properly (not raw in the prompt). The agent runs in a
background thread so the UI never freezes while it thinks.

The app takes a `responder(text) -> reply` callable, so it can be driven by the
real agent in production and by a stub in tests.
"""

from __future__ import annotations

from typing import Callable

from rich.markdown import Markdown
from rich.panel import Panel
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Input, RichLog, Static, TextArea


class EklavyaApp(App):
    TITLE = "Ekalavya"

    CSS = """
    #stats { dock: top; height: 1; background: $panel; color: $accent; padding: 0 1; }
    #log { border: round $primary; padding: 0 1; }
    #editor { display: none; height: 12; border: round $secondary; }
    #editor.on { display: block; }
    #streaming { display: none; }
    #streaming.live { display: block; }
    #msg { dock: bottom; }
    """

    BINDINGS = [
        ("ctrl+e", "toggle_editor", "Code editor"),
        ("ctrl+s", "submit_code", "Submit code"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, responder: Callable[[str], str], stats_fn: Callable[[], dict] | None = None,
                 kickoff: str = "", use_worker: bool = True, guard: bool = True,
                 stream_fn: Callable[[str], object] | None = None) -> None:
        super().__init__()
        self.responder = responder
        self.stream_fn = stream_fn  # optional: yields reply tokens for live streaming
        self.stats_fn = stats_fn
        self.kickoff = kickoff
        self.use_worker = use_worker
        self.guard = guard  # anti-cheat on?
        self.history: list[tuple[str, str]] = []  # (role, text) — for tests + record
        self.pastes = 0            # total editor pastes seen
        self._editor_pasted = False  # was the current editor buffer pasted into?

    def compose(self) -> ComposeResult:
        yield Static("🏹 Ekalavya", id="stats")
        with Vertical():
            yield RichLog(id="log", wrap=True, markup=True, highlight=False)
            yield Static("", id="streaming")
            yield TextArea.code_editor("", language="python", id="editor")
            yield Input(placeholder="type your answer…  (Ctrl+E to open the code editor)", id="msg")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_stats()
        if self.kickoff:
            self.send(self.kickoff, show=False)

    # --- rendering ---------------------------------------------------------

    def _refresh_stats(self) -> None:
        if not self.stats_fn:
            return
        s = self.stats_fn()
        self.query_one("#stats", Static).update(
            f"🏹 Ekalavya    🔥 streak {s['streak']}    ⭐ level {s['level']}    {s['xp']} XP"
        )

    def _write_user(self, text: str) -> None:
        self.query_one("#log", RichLog).write(Panel(text, title="you", border_style="green", title_align="left"))

    def _write_agent(self, text: str) -> None:
        self.query_one("#log", RichLog).write(
            Panel(Markdown(text), title="Ekalavya", border_style="cyan", title_align="left")
        )

    # --- sending -----------------------------------------------------------

    def send(self, text: str, show: bool = True) -> None:
        if show:
            self.history.append(("user", text))
            self._write_user(text)
        msg = self.query_one("#msg", Input)
        msg.disabled = True
        msg.placeholder = "thinking…"
        if self.stream_fn:
            self._stream_worker(text) if self.use_worker else self._stream_sync(text)
        elif self.use_worker:
            self._respond(text)
        else:  # synchronous path for tests
            self._deliver(self.responder(text))

    @work(thread=True, exclusive=True)
    def _respond(self, text: str) -> None:
        reply = self.responder(text)
        self.call_from_thread(self._deliver, reply)

    @work(thread=True, exclusive=True)
    def _stream_worker(self, text: str) -> None:
        buf: list[str] = []
        self.call_from_thread(self._stream_start)
        for token in self.stream_fn(text):
            buf.append(token)
            self.call_from_thread(self._stream_update, "".join(buf))
        self.call_from_thread(self._stream_end, "".join(buf))

    def _stream_sync(self, text: str) -> None:
        buf: list[str] = []
        self._stream_start()
        for token in self.stream_fn(text):
            buf.append(token)
            self._stream_update("".join(buf))
        self._stream_end("".join(buf))

    def _stream_start(self) -> None:
        self.query_one("#streaming", Static).add_class("live")

    def _stream_update(self, text: str) -> None:
        self.query_one("#streaming", Static).update(
            Panel(text, title="[cyan]Ekalavya…[/]", border_style="cyan", title_align="left")
        )

    def _stream_end(self, text: str) -> None:
        streaming = self.query_one("#streaming", Static)
        streaming.remove_class("live")
        streaming.update("")
        self._deliver(text)  # finalize as a rendered markdown panel in the log

    def _deliver(self, reply: str) -> None:
        self.history.append(("agent", reply))
        self._write_agent(reply)
        self._refresh_stats()
        msg = self.query_one("#msg", Input)
        msg.disabled = False
        msg.placeholder = "type your answer…  (Ctrl+E to open the code editor)"
        msg.focus()

    # --- events & actions --------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        self.query_one("#msg", Input).value = ""
        self.send(text)

    def on_paste(self, event) -> None:
        # The built-in editor is our honest-signal surface: a paste into an open
        # editor is the tell we watch for.
        if self.query_one("#editor", TextArea).has_class("on"):
            self.pastes += 1
            self._editor_pasted = True

    def action_toggle_editor(self) -> None:
        editor = self.query_one("#editor", TextArea)
        editor.toggle_class("on")
        if editor.has_class("on"):
            self._editor_pasted = False  # fresh buffer
            editor.focus()
        else:
            self.query_one("#msg", Input).focus()

    def action_submit_code(self) -> None:
        editor = self.query_one("#editor", TextArea)
        code = editor.text.strip()
        if not code:
            return
        pasted = self._editor_pasted
        editor.text = ""
        editor.remove_class("on")
        self._editor_pasted = False
        if self.guard and pasted:
            self._souls_death("code was pasted into the editor")
            return  # the point is to practice — a pasted answer isn't one
        if self.guard:
            self._maybe_reclaim()  # typed it yourself → reclaim any dropped souls
        self.send(f"Here is my code:\n```python\n{code}\n```")

    def _souls_death(self, reason: str) -> None:
        from . import progress

        result = progress.penalise(reason)
        self.history.append(("death", reason))
        self.query_one("#log", RichLog).write(
            Panel(
                f"[bold red]YOU DIED[/]\n\n{reason}.\n"
                f"Souls dropped: [red]-{result['lost']} XP[/]. Streak broken.\n"
                "[dim]Type your next answer yourself to reclaim your souls.[/]",
                border_style="red", title="⚰  caught", title_align="left",
            )
        )
        self._refresh_stats()

    def _maybe_reclaim(self) -> None:
        from . import progress

        amount = progress.reclaim()
        if amount:
            self.history.append(("reclaim", str(amount)))
            self.query_one("#log", RichLog).write(
                Panel(
                    f"[bold green]SOULS RECLAIMED[/]  +{amount} XP\n"
                    "[dim]You typed it yourself. That's the whole point.[/]",
                    border_style="green", title="⚔  recovered", title_align="left",
                )
            )
            self._refresh_stats()


def make_responder(agent, config) -> Callable[[str], str]:
    """Wrap a deepagents agent + thread config into a simple text->text responder."""
    from .chat import run_turn

    def respond(text: str) -> str:
        return run_turn(agent, config, text)

    return respond


def _chunk_text(message_chunk) -> str:
    """Pull visible text out of a streamed AIMessageChunk (content is text blocks)."""
    content = message_chunk.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def make_stream_responder(agent, config):
    """Yield the agent's reply token-by-token for live streaming in the UI."""

    def stream(text: str):
        for message_chunk, _meta in agent.stream(
            {"messages": [{"role": "user", "content": text}]},
            config=config,
            stream_mode="messages",
        ):
            token = _chunk_text(message_chunk)
            if token:
                yield token

    return stream
