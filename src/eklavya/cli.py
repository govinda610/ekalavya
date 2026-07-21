"""The `eklavya` command-line entry point.

P0 surface: `eklavya` (splash), `version`, `init`, `doctor`. Practice commands
(`onboard`, `drill`, `tui`, `serve`) arrive with later phases.
"""

from __future__ import annotations

import importlib.util
import platform
import sys

import typer
from rich.console import Console
from rich.table import Table

from . import __version__, banner, config
from .db import init_db, schema_version
from .providers import PROVIDERS, configured_providers

app = typer.Typer(
    add_completion=False,
    help="Ekalavya — an AI coding tutor. Swadhyaya · Sadhana · Siddhi.",
    no_args_is_help=False,
)
console = Console()


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context) -> None:
    """Bare `eklavya`: onboard on the first run, else jump straight into practice."""
    if ctx.invoked_subcommand is not None:
        return
    init_db()
    if _first_run():
        console.print("[dim]Welcome — first run. Let's build your baseline.[/]\n")
        onboard(provider=None)
    else:
        tui(minutes=30, provider=None, guard=True)


def _first_run() -> bool:
    from .report import is_first_run

    return is_first_run()


def _configured_provider(provider):
    """Warm the MCP tools (sync) so terminal agents get web search + docs too, then
    return a configured provider — or exit with a friendly message."""
    from .mcp_client import load_mcp_tools
    from .providers import pick

    load_mcp_tools()
    p = _configured_provider(provider)
    return p


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"eklavya {__version__}")


@app.command()
def init() -> None:
    """Create the tutor's home and database."""
    home = config.ensure_home()
    db = init_db()
    console.print(f"[green]✓[/green] home:     {home}")
    console.print(f"[green]✓[/green] database: {db}")
    console.print("\nReady. Onboarding lands in the next phase.")


@app.command()
def onboard(
    provider: str = typer.Option(None, help="glm or minimax (default: glm)"),
) -> None:
    """First-time onboarding — a Socratic interview that builds your baseline."""
    from . import prompts
    from .agent import build_agent
    from .chat import chat_loop
    from .providers import pick
    from .tools import ONBOARDING_TOOLS

    init_db()  # make sure state exists
    p = _configured_provider(provider)

    banner.render(console)
    console.print(f"\n[dim]teacher: {p.label} · {p.default_model}[/]\n")
    agent = build_agent(prompts.ONBOARDING, ONBOARDING_TOOLS, provider=p.key)
    chat_loop(agent, kickoff="Begin my first-time onboarding now.", console=console, mode="onboard")


@app.command()
def mock(
    minutes: int = typer.Option(45, help="how long you have"),
    provider: str = typer.Option(None, help="glm or minimax (default: glm)"),
) -> None:
    """A mock technical interview — coding / design / behavioral, with a scorecard."""
    from . import progress, prompts
    from .agent import build_agent
    from .chat import chat_loop
    from .providers import pick
    from .tools import SESSION_TOOLS

    init_db()
    p = _configured_provider(provider)

    banner.render(console)
    console.print(f"\n[dim]interviewer: {p.label} · {p.default_model} · {minutes} min[/]\n")
    agent = build_agent(prompts.MOCK, SESSION_TOOLS, provider=p.key)
    progress.start_session(minutes, mode="mock")
    try:
        chat_loop(agent, kickoff=f"Start a mock interview. I have {minutes} minutes.",
                  console=console, mode="mock")
    finally:
        progress.end_session()


@app.command()
def practice(
    minutes: int = typer.Option(30, help="how long you have today"),
    provider: str = typer.Option(None, help="glm or minimax (default: glm)"),
) -> None:
    """A daily practice session — gated drills tuned to your weak spots."""
    from . import prompts
    from .agent import build_agent
    from .chat import chat_loop
    from .providers import pick
    from .tools import SESSION_TOOLS

    init_db()
    p = _configured_provider(provider)

    from . import progress

    banner.render(console)
    console.print(f"\n[dim]teacher: {p.label} · {p.default_model} · {minutes} min[/]\n")
    agent = build_agent(prompts.SESSION, SESSION_TOOLS, provider=p.key)
    progress.start_session(minutes)
    try:
        chat_loop(agent, kickoff=f"Start today's practice session. I have {minutes} minutes.",
                  console=console, mode="practice")
    finally:
        progress.end_session()


@app.command()
def tui(
    minutes: int = typer.Option(30, help="how long you have today"),
    provider: str = typer.Option(None, help="glm or minimax (default: glm)"),
    guard: bool = typer.Option(True, help="anti-cheat: penalise pasted code (Souls-like)"),
) -> None:
    """The immersive terminal UI — practice with a built-in code editor."""
    from . import progress, prompts
    from .agent import build_agent
    from .chat import new_thread
    from .providers import pick
    from .tools import SESSION_TOOLS
    from .tui import EklavyaApp, make_responder, make_stream_responder

    init_db()
    p = _configured_provider(provider)

    agent = build_agent(prompts.SESSION, SESSION_TOOLS, provider=p.key)
    config = new_thread()
    from .chatstore import touch_chat

    touch_chat(config["configurable"]["thread_id"], mode="practice")  # register in history
    tui_app = EklavyaApp(
        responder=make_responder(agent, config),
        stream_fn=make_stream_responder(agent, config),
        stats_fn=progress.stats,
        kickoff=f"Start today's practice session. I have {minutes} minutes.",
        guard=guard,
    )
    progress.start_session(minutes)
    try:
        tui_app.run()
    finally:
        progress.end_session()


@app.command()
def takehome(
    minutes: int = typer.Option(90, help="how long you have for the assignment"),
    provider: str = typer.Option(None, help="glm or minimax (default: glm)"),
) -> None:
    """Simulate a company take-home assignment, then get reviewed like the real thing."""
    from . import progress, prompts
    from .agent import build_agent
    from .chat import chat_loop
    from .providers import pick
    from .tools import SESSION_TOOLS

    init_db()
    p = _configured_provider(provider)

    banner.render(console)
    console.print(f"\n[dim]interviewer: {p.label} · {p.default_model} · {minutes} min take-home[/]\n")
    agent = build_agent(prompts.TAKEHOME, SESSION_TOOLS, provider=p.key)
    progress.start_session(minutes, mode="takehome")
    try:
        chat_loop(agent, kickoff=f"Give me a take-home assignment. I have {minutes} minutes.",
                  console=console, mode="takehome")
    finally:
        progress.end_session()


def _mode_agent(mode: str):
    """(prompt, tools) for a chat's mode, used to rebuild the agent when resuming.
    (Temporary duplication with webapp; #40 unifies the agent across interfaces.)"""
    from . import prompts
    from .tools import AIINTERVIEW_TOOLS, ONBOARDING_TOOLS, SESSION_TOOLS

    table = {
        "practice": (prompts.SESSION, SESSION_TOOLS),
        "mock": (prompts.MOCK, SESSION_TOOLS),
        "aiinterview": (prompts.AI_INTERVIEW, AIINTERVIEW_TOOLS),
        "takehome": (prompts.TAKEHOME, SESSION_TOOLS),
        "onboard": (prompts.ONBOARDING, ONBOARDING_TOOLS),
    }
    return table.get(mode, (prompts.SESSION, SESSION_TOOLS))


@app.command()
def chats() -> None:
    """List your past chats (resume one with `eklavya resume <#>`)."""
    from .chatstore import list_chats

    init_db()
    rows = list_chats()
    if not rows:
        console.print("[dim]No past chats yet.[/]")
        return
    table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    table.add_column("#")
    table.add_column("chat")
    table.add_column("mode")
    table.add_column("updated")
    for i, c in enumerate(rows, 1):
        table.add_row(str(i), c["title"] or "(untitled)", c["mode"] or "", (c["updated_at"] or "")[:16])
    console.print(table)
    console.print("\n[dim]resume with:  eklavya resume <#>[/]")


@app.command()
def resume(n: int = typer.Argument(1, help="which chat (1 = most recent; see `eklavya chats`)")) -> None:
    """Resume a past chat and continue it (most recent by default)."""
    from .agent import build_agent
    from .chat import chat_loop
    from .chatstore import list_chats, transcript
    from .providers import pick

    init_db()
    rows = list_chats()
    if not rows:
        console.print("[dim]No past chats to resume.[/]")
        raise typer.Exit()
    if n < 1 or n > len(rows):
        console.print(f"[red]✗[/red] pick a number between 1 and {len(rows)} (see `eklavya chats`).")
        raise typer.Exit(1)
    c = rows[n - 1]
    p = _configured_provider(None)
    prompt, tools = _mode_agent(c["mode"])
    agent = build_agent(prompt, tools, provider=p.key)
    banner.render(console)
    console.print(f"\n[dim]resuming:[/] [bold]{c['title'] or c['mode']}[/]  ({c['mode']})\n")
    chat_loop(agent, kickoff=None, console=console,
              config={"configurable": {"thread_id": c["thread_id"]}},
              mode=c["mode"], replay=transcript(c["thread_id"]))


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="bind host"),
    port: int = typer.Option(4646, help="bind port"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="open the browser automatically"),
) -> None:
    """Open the full web app — practice in the browser, no terminal needed."""
    import uvicorn

    from .mcp_client import load_mcp_tools
    from .webapp import create_app

    init_db()
    load_mcp_tools()  # warm MCP tools (sync) so web agents get web search + docs
    url = f"http://{host}:{port}"
    console.print(f"[green]›[/green] Ekalavya at [bold]{url}[/bold]  (Ctrl+C to stop)")
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.2, lambda: webbrowser.open(url)).start()  # after the server is up
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


@app.command("mcp")
def mcp_server() -> None:
    """Run Ekalavya as an MCP server (stdio) so any agent can drive your practice."""
    from .mcp_server import run

    run()  # blocks; stdout is the MCP wire, so we print nothing


@app.command()
def scan(path: str = typer.Argument(..., help="path to a repo you allow Ekalavya to read")) -> None:
    """Tailor your pillars to a repo you work on (asks permission first)."""
    from pathlib import Path

    from . import repos
    from .tools import add_pillar

    target = Path(path).expanduser().resolve()
    if not target.exists():
        console.print(f"[red]✗[/red] no such path: {target}")
        raise typer.Exit(1)

    console.print(f"Ekalavya will read dependency files and imports under:\n  [bold]{target}[/bold]")
    if not typer.confirm("Allow reading this repo?"):
        console.print("[dim]skipped.[/]")
        raise typer.Exit()

    init_db()
    found = repos.detect(target)
    if not found["pillars"]:
        console.print("[dim]No familiar stacks detected.[/]")
    else:
        console.print("\n[bold]Detected:[/bold] " + ", ".join(found["stacks"]))
        console.print("[bold]Suggested pillars:[/bold] " + ", ".join(found["pillars"]))
        if typer.confirm("Add these pillars to your practice?", default=True):
            for pillar in found["pillars"]:
                add_pillar(pillar)
    repos.grant(target, ",".join(found["stacks"]), ",".join(found["pillars"]))
    console.print("[green]✓[/green] repo recorded.")


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


@app.command()
def doctor() -> None:
    """Check the environment: Python, dependencies, providers, and state."""
    banner.render(console)
    console.print()

    ok = "[green]✓[/green]"
    no = "[red]✗[/red]"
    warn = "[yellow]•[/yellow]"

    # --- Runtime -------------------------------------------------------------
    py = platform.python_version()
    py_ok = sys.version_info[:2] >= (3, 11)
    console.print(f"{ok if py_ok else no} Python {py}  (need ≥ 3.11)")

    # --- Dependency stack ----------------------------------------------------
    core = {"typer": "typer", "rich": "rich", "dotenv": "python-dotenv"}
    agent = {
        "deepagents": "deepagents",
        "langchain": "langchain",
        "langgraph": "langgraph",
        "langchain_anthropic": "langchain-anthropic",
        "fsrs": "fsrs",
    }
    dep_table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    dep_table.add_column("dependency")
    dep_table.add_column("status")
    for module, dist in core.items():
        present = _has_module(module)
        dep_table.add_row(dist, f"{ok} installed" if present else f"{no} missing (core)")
    for module, dist in agent.items():
        present = _has_module(module)
        dep_table.add_row(
            dist,
            f"{ok} installed" if present else f"{warn} not yet (uv sync --extra agent)",
        )
    console.print(dep_table)
    console.print()

    # --- Providers -----------------------------------------------------------
    prov_table = Table(show_header=True, header_style="bold cyan", box=None, pad_edge=False)
    prov_table.add_column("provider")
    prov_table.add_column("default model")
    prov_table.add_column("token")
    for p in PROVIDERS.values():
        prov_table.add_row(
            p.label,
            p.default_model,
            f"{ok} configured" if p.is_configured() else f"{no} set {p.token_env[0]} in .env",
        )
    console.print(prov_table)
    if not configured_providers():
        console.print(
            f"\n{warn} No provider configured yet — copy [bold].env.example[/bold] to "
            "[bold].env[/bold] and add a key."
        )
    console.print()

    # --- State ---------------------------------------------------------------
    ver = schema_version()
    if ver:
        console.print(f"{ok} database ready (schema v{ver}) at {config.DB_PATH}")
    else:
        console.print(f"{warn} database not initialised — run [bold]eklavya init[/bold]")
    prof = config.PROFILE_PATH
    if prof.exists():
        console.print(f"{ok} learner profile found (shared with Teacher Mode): {prof}")
    else:
        console.print(f"{warn} no learner profile yet (created at onboarding): {prof}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
