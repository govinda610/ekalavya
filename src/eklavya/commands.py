"""In-session slash commands — handled locally, no model call (the Claude Code pattern).

`handle_slash(text)` returns:
  - None              → not a slash command; let the agent handle the message
  - EXIT              → the user asked to leave
  - any other string  → output to display (help, stats, goals, …)

Prefix matching means `/st` resolves to `/stats`, like the agents people know.
"""

from __future__ import annotations

EXIT = "__exit__"

# name -> one-line description (shown by /help)
_COMMANDS = {
    "help": "list commands",
    "stats": "your streak, level, XP and mastery map",
    "goals": "your active goals",
    "exit": "leave the session (progress is saved)",
}


def _help() -> str:
    lines = ["Commands — type `/` then the name (prefixes work, e.g. `/st`):"]
    lines += [f"  /{name:<7} {desc}" for name, desc in _COMMANDS.items()]
    return "\n".join(lines)


def resolve(name: str) -> str | None:
    """Resolve a possibly-abbreviated command name via exact-or-prefix match."""
    name = name.lower()
    if name in _COMMANDS:
        return name
    matches = [c for c in _COMMANDS if c.startswith(name)]
    return matches[0] if matches else None


def handle_slash(text: str) -> str | None:
    text = text.strip()
    if not text.startswith("/"):
        return None
    raw = text[1:].split()[0].lower() if text[1:].split() else "help"
    if raw in ("exit", "quit", "q"):
        return EXIT
    name = resolve(raw)
    if name is None:
        return f"Unknown command `/{raw}`.\n{_help()}"
    if name == "help":
        return _help()
    if name == "stats":
        from .tools import progress_report

        return progress_report()
    if name == "goals":
        from .tools import list_goals

        return "Your goals:\n" + list_goals()
    return _help()
