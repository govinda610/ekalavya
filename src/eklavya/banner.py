"""The splash — Ekalavya's creed, shown on launch."""

from __future__ import annotations

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

_ART = r"""
 ___  _  _  __    __    _  _  ___  _  _  __
(  _)( )/ )(  )  /__\  ( \/ )/ __)( )/ )/  \
 ) _) )  (  )(__ /(__)\ \  / \__ \ )  ((  ) )
(___)(_)\_)(____)(__)(__)(__) (___/(_)\_)\__/
"""

CREED = "स्वाध्याय · साधना · सिद्धि"
CREED_ROMAN = "Swadhyaya · Sadhana · Siddhi  —  Self-study · Devoted practice · Mastery"


def render(console: Console | None = None) -> None:
    console = console or Console()
    body = Text(justify="center")
    body.append(_ART.strip("\n"), style="bold green")
    body.append("\n\n")
    body.append("»———►  ", style="green")
    body.append(CREED, style="bold cyan")
    body.append("  ◄———«", style="green")
    body.append("\n")
    body.append(CREED_ROMAN, style="dim italic")
    console.print(
        Panel(
            Align.center(body),
            border_style="green",
            title="[bold]🏹 Ekalavya[/bold]",
            subtitle="[dim]an AI coding tutor[/dim]",
            padding=(1, 3),
            expand=False,
        )
    )
