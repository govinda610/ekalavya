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
    """Show the splash when called with no subcommand."""
    if ctx.invoked_subcommand is None:
        banner.render(console)
        console.print(
            "\n  Run [bold green]eklavya doctor[/bold green] to check your setup, "
            "or [bold green]eklavya --help[/bold green] for commands.\n"
        )


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
    from .providers import get_provider
    from .tools import ONBOARDING_TOOLS

    init_db()  # make sure state exists
    p = get_provider(provider)
    if not p.is_configured():
        console.print(f"[red]✗[/red] {p.label} has no key. Add {p.token_env[0]} to .env.")
        raise typer.Exit(1)

    banner.render(console)
    console.print(f"\n[dim]teacher: {p.label} · {p.default_model}[/]\n")
    agent = build_agent(prompts.ONBOARDING, ONBOARDING_TOOLS, provider=provider)
    chat_loop(agent, kickoff="Begin my first-time onboarding now.", console=console)


@app.command()
def practice(
    minutes: int = typer.Option(30, help="how long you have today"),
    provider: str = typer.Option(None, help="glm or minimax (default: glm)"),
) -> None:
    """A daily practice session — gated drills tuned to your weak spots."""
    from . import prompts
    from .agent import build_agent
    from .chat import chat_loop
    from .providers import get_provider
    from .tools import SESSION_TOOLS

    init_db()
    p = get_provider(provider)
    if not p.is_configured():
        console.print(f"[red]✗[/red] {p.label} has no key. Add {p.token_env[0]} to .env.")
        raise typer.Exit(1)

    from . import progress

    banner.render(console)
    console.print(f"\n[dim]teacher: {p.label} · {p.default_model} · {minutes} min[/]\n")
    agent = build_agent(prompts.SESSION, SESSION_TOOLS, provider=provider)
    progress.start_session(minutes)
    try:
        chat_loop(agent, kickoff=f"Start today's practice session. I have {minutes} minutes.",
                  console=console)
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
    from .providers import get_provider
    from .tools import SESSION_TOOLS
    from .tui import EklavyaApp, make_responder

    init_db()
    p = get_provider(provider)
    if not p.is_configured():
        console.print(f"[red]✗[/red] {p.label} has no key. Add {p.token_env[0]} to .env.")
        raise typer.Exit(1)

    agent = build_agent(prompts.SESSION, SESSION_TOOLS, provider=provider)
    responder = make_responder(agent, new_thread())
    tui_app = EklavyaApp(
        responder=responder,
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
def serve(
    host: str = typer.Option("127.0.0.1", help="bind host"),
    port: int = typer.Option(4646, help="bind port"),
) -> None:
    """Open the local web dashboard — your mastery map, streak, and progress."""
    import uvicorn

    from .dashboard import create_app

    init_db()
    console.print(f"[green]›[/green] dashboard at [bold]http://{host}:{port}[/bold]  (Ctrl+C to stop)")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


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
