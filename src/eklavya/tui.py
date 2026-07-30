"""The immersive terminal UI — a chat with the tutor plus a built-in code editor.

Kept simple: a scrolling conversation, an input line, and a togglable Python
editor so you write code properly (not raw in the prompt). The agent runs in a
background thread so the UI never freezes while it thinks.

The app takes a `responder(text) -> reply` callable, so it can be driven by the
real agent in production and by a stub in tests.
"""

from __future__ import annotations

import threading
from typing import Callable

from rich.markdown import Markdown
from rich.panel import Panel
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Footer, Input, Label, RichLog, Static, TextArea

from .commands import EXIT, handle_slash

# One brand theme, shared with the dashboard's palette (centralized theming).
EKALAVYA_THEME = Theme(
    name="ekalavya",
    primary="#5ef2b8",
    secondary="#57d3ff",
    accent="#ffcf6b",
    foreground="#d6e2f0",
    background="#080b11",
    surface="#111a28",
    panel="#0e1622",
    success="#5ef2b8",
    warning="#ffcf6b",
    error="#ff5c7a",
    dark=True,
)


def _rank(level: int) -> str:
    for threshold, name in ((17, "Grandmaster"), (12, "Master"), (8, "Expert"),
                            (5, "Adept"), (3, "Apprentice"), (1, "Novice")):
        if level >= threshold:
            return name
    return "Novice"


class ApprovalScreen(ModalScreen[bool]):
    """Asks the learner to approve a run_bash command before it executes.

    Mirrors the web app's approval card and the CLI's y/N prompt: nothing runs
    without consent. Dismisses with True (approve) or False (reject); Esc rejects.
    """

    CSS = """
    ApprovalScreen { align: center middle; }
    #approve-box {
        width: 72; max-width: 90%; height: auto; padding: 1 2;
        border: round $warning; background: $panel;
    }
    #approve-title { color: $warning; text-style: bold; margin-bottom: 1; }
    #approve-cmd {
        background: $surface; color: $foreground; border: round $secondary;
        padding: 0 1; margin-bottom: 1;
    }
    #approve-why { color: $foreground; margin-bottom: 1; }
    #approve-btns { height: auto; align-horizontal: center; }
    #approve-btns Button { margin: 0 1; }
    """

    BINDINGS = [("escape", "reject", "Reject")]

    def __init__(self, command: str, explanation: str) -> None:
        super().__init__()
        self._command = command
        self._explanation = explanation

    def compose(self) -> ComposeResult:
        with Vertical(id="approve-box"):
            yield Label("⏻ Run this command?", id="approve-title")
            yield Static(self._command or "(empty command)", id="approve-cmd")
            if self._explanation:
                yield Static(self._explanation, id="approve-why")
            with Vertical(id="approve-btns"):
                yield Button("Approve", variant="success", id="approve-yes")
                yield Button("Reject", variant="error", id="approve-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve-yes")

    def action_reject(self) -> None:
        self.dismiss(False)


class EklavyaApp(App):
    TITLE = "Ekalavya"

    CSS = """
    Screen { background: $background; }
    #stats { dock: top; height: 1; background: $panel; color: $foreground; padding: 0 1; }
    #log { border: round $primary; background: $surface; padding: 0 1; }
    #editor { display: none; height: 12; border: round $secondary; background: $surface; }
    #editor.on { display: block; }
    #streaming { display: none; }
    #streaming.live { display: block; height: auto; }
    #msg { dock: bottom; }
    """

    BINDINGS = [
        ("ctrl+e", "toggle_editor", "Code editor"),
        ("ctrl+s", "submit_code", "Submit code"),
        ("ctrl+g", "toggle_penalty", "Penalty on/off"),
        ("escape", "cancel", "Cancel reply"),
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
        self.guard = guard  # anti-cheat detection on?
        from . import settings

        self.death_on_cheat = settings.get_death_on_cheat()  # penalise, or just a quiet note?
        self.history: list[tuple[str, str]] = []  # (role, text) — for tests + record
        self.pastes = 0            # total editor pastes seen
        self._biggest_paste = 0    # chars in the largest paste into the current editor buffer
        self._in_flight = False    # a response is streaming/thinking (Esc can cancel it)

    def compose(self) -> ComposeResult:
        yield Static("🏹 Ekalavya", id="stats")
        with Vertical():
            yield RichLog(id="log", wrap=True, markup=True, highlight=False)
            yield Static("", id="streaming")
            yield TextArea.code_editor("", language="python", id="editor")
            yield Input(placeholder="type your answer…  (Ctrl+E to open the code editor)", id="msg")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(EKALAVYA_THEME)
        self.theme = "ekalavya"
        self._refresh_stats()
        if self.kickoff:
            self.send(self.kickoff, show=False)

    # --- rendering ---------------------------------------------------------

    def _refresh_stats(self) -> None:
        if not self.stats_fn:
            return
        s = self.stats_fn()
        into = s["xp"] % 100
        filled = round(into / 10)
        bar = "█" * filled + "░" * (10 - filled)
        self.query_one("#stats", Static).update(
            f"🏹 [b]Ekalavya[/]   🔥 [#ffcf6b]{s['streak']}[/]   "
            f"⭐ Lv [b]{s['level']}[/] [#b48cff]{_rank(s['level'])}[/]   "
            f"[#5ef2b8]{bar}[/] [dim]{into}/100[/]"
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
        msg.placeholder = "thinking…  (Esc to cancel)"
        if self.stream_fn:
            if self.use_worker:
                self._in_flight = True
                self._stream_worker(text)
            else:
                self._stream_sync(text)
        elif self.use_worker:
            self._in_flight = True
            self._respond(text)
        else:  # synchronous path for tests
            self._deliver(self.responder(text))

    @work(thread=True, exclusive=True)
    def _respond(self, text: str) -> None:
        reply = self.responder(text)
        self.call_from_thread(self._deliver, reply)

    @work(thread=True, exclusive=True)
    def _stream_worker(self, text: str) -> None:
        from .verify import selfcheck

        buf: list[str] = []
        self.call_from_thread(self._stream_start)
        for token in self.stream_fn(text):
            buf.append(token)
            self.call_from_thread(self._stream_update, "".join(buf))
        full = "".join(buf)
        self.call_from_thread(self._stream_end, full)
        note = selfcheck(full, context=text)  # blocking model call, but we're on the worker thread
        if note:
            self.call_from_thread(self._write_agent, note)

    def ask_bash_approval(self, command: str, explanation: str) -> bool:
        """Show the approval modal and BLOCK until the learner decides.

        Called from the streaming worker thread. It hops to the UI thread to push
        the modal, then waits on an Event that the modal's result callback sets, so
        run_bash never runs in the TUI without consent. Safe default: reject."""
        decided = threading.Event()
        result = {"approved": False}

        def _on_result(approved: bool | None) -> None:
            result["approved"] = bool(approved)
            decided.set()

        def _push() -> None:
            self.push_screen(ApprovalScreen(command, explanation), _on_result)

        self.call_from_thread(_push)
        decided.wait()
        return result["approved"]

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
        self._in_flight = False
        self.history.append(("agent", reply))
        self._write_agent(reply)
        self._refresh_stats()
        msg = self.query_one("#msg", Input)
        msg.disabled = False
        msg.placeholder = "type your answer…  (Ctrl+E to open the code editor)"
        msg.focus()

    def action_cancel(self) -> None:
        """Esc — cancel an in-flight agent response and re-open the input.

        No-op when nothing is streaming (so Esc doesn't clobber an idle UI). The
        thread worker can't be force-killed, but cancelling it makes its next
        `call_from_thread` raise, unwinding it cleanly; we reset the UI here."""
        if not self._in_flight:
            return
        self._in_flight = False
        self.workers.cancel_all()
        streaming = self.query_one("#streaming", Static)
        streaming.remove_class("live")
        streaming.update("")
        self.query_one("#log", RichLog).write(
            Panel("[dim]response cancelled.[/]", border_style="yellow", title_align="left")
        )
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
        slash = handle_slash(text)
        if slash is not None:
            if slash == EXIT:
                self.exit()
            else:
                self.query_one("#log", RichLog).write(
                    Panel(slash, border_style="magenta", title="[magenta]/[/]", title_align="left")
                )
            return
        self.send(text)

    def on_paste(self, event) -> None:
        # The editor is our honest-signal surface. We don't treat any paste as
        # cheating — we just remember the biggest one; only a large paste that
        # dominates the submitted solution is later flagged.
        if self.query_one("#editor", TextArea).has_class("on"):
            self.pastes += 1
            self._biggest_paste = max(self._biggest_paste, len(getattr(event, "text", "") or ""))

    def on_text_area_changed(self, event) -> None:
        # If the pasted block was deleted, forget it (avoids false positives).
        if len(event.text_area.text) < self._biggest_paste:
            self._biggest_paste = 0

    def action_toggle_editor(self) -> None:
        editor = self.query_one("#editor", TextArea)
        editor.toggle_class("on")
        if editor.has_class("on"):
            self._biggest_paste = 0  # fresh buffer
            editor.focus()
        else:
            self.query_one("#msg", Input).focus()

    def action_submit_code(self) -> None:
        from . import progress

        editor = self.query_one("#editor", TextArea)
        code = editor.text.strip()
        if not code:
            return
        if self.guard and progress.looks_pasted(code, self._biggest_paste):
            self._flag_cheat("a full solution was pasted into the editor")
            return  # keep the code on-screen — never wipe on a (possibly false) trigger
        editor.text = ""
        editor.remove_class("on")
        self._biggest_paste = 0
        if self.guard:
            self._maybe_reclaim()  # typed it yourself → reclaim any dropped souls
        self.send(f"Here is my code:\n```python\n{code}\n```")

    def action_toggle_penalty(self) -> None:
        from . import settings

        self.death_on_cheat = not self.death_on_cheat
        settings.set_death_on_cheat(self.death_on_cheat)
        self._write_agent(f"Cheat penalty is now **{'on' if self.death_on_cheat else 'off'}**.")

    def _flag_cheat(self, reason: str) -> None:
        from . import progress

        if not self.death_on_cheat:  # penalty off → a quiet note, no punishment, code untouched
            self._write_agent(f"⚠ {reason} — noticed, but the penalty is off, so nothing happens.")
            return
        result = progress.penalise(reason)
        self.history.append(("death", reason))
        self.query_one("#log", RichLog).write(
            Panel(
                f"[bold red]YOU DIED[/]\n\n{reason}.\n"
                f"Souls dropped: [red]-{result['lost']} XP[/]. Streak broken.\n"
                "[dim]Your code stays. Type your next answer yourself to reclaim your souls.[/]",
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


def make_stream_responder(agent, config, approve: Callable[[str, str], bool] | None = None):
    """Yield the agent's reply token-by-token for live streaming in the UI.

    When the agent calls run_bash, the run pauses on an interrupt. `approve` is a
    callback `(command, explanation) -> bool` that asks the learner (via the
    Textual approval modal) whether to run it; the interrupt is then resumed with
    the matching decision. When `approve` is None (e.g. tests), commands are
    rejected — nothing runs without consent."""
    from langgraph.types import Command

    from .agent import pending_bash_approval

    def stream(text: str):
        inputs = {"messages": [{"role": "user", "content": text}]}
        while True:
            for message_chunk, _meta in agent.stream(inputs, config=config, stream_mode="messages"):
                token = _chunk_text(message_chunk)
                if token:
                    yield token
            appr = pending_bash_approval(agent, config)
            if appr is None:
                break
            ok = approve(appr["command"], appr["explanation"]) if approve else False
            decision = "approve" if ok else "reject"
            if not ok:
                yield "\n\n_(command rejected — nothing ran)_\n"
            inputs = Command(resume={"decisions": [{"type": decision}]})

    return stream
