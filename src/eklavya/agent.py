"""Build the deepagents agent that does the teaching.

The agent is the brain (Socratic conversation, judgement); the tools are the
reliable hands (state, ratings, goals). We pass a GLM/MiniMax model instance and
a checkpointer so a conversation persists across turns on one thread_id.
"""

from __future__ import annotations

import re

from .fallback import build_fallback_chat_model

# A teaching turn can be long (explanations, code); give it room.
_MAX_TOKENS = 4096

# deepagents adds a builtin `execute` shell tool to every agent. We deliberately
# do NOT want the model to have it: all shell work goes through our own approval-
# gated `run_bash` tool. Excluding it at the source (rather than only asking the
# model not to call it in the prompt) is registered via a harness profile keyed on
# the model's resolved provider. Our FallbackChatModel always reports
# `ls_provider="fallbackchatmodel"`, so that key matches every session regardless
# of the underlying provider/model. Registration is additive and idempotent, so
# importing this module more than once is safe.
_EXECUTE_EXCLUDED = False


def _exclude_execute_tool() -> None:
    """Register a harness profile that drops the builtin `execute` tool.

    deepagents' documented way to remove a builtin tool is a HarnessProfile with
    `excluded_tools`; a `_ToolExclusionMiddleware` then filters it from the tool
    set the model sees (`wrap_model_call`), so the model can never call it.
    """
    global _EXECUTE_EXCLUDED
    if _EXECUTE_EXCLUDED:
        return
    from deepagents import HarnessProfile, register_harness_profile

    register_harness_profile(
        "fallbackchatmodel",
        HarnessProfile(excluded_tools=frozenset({"execute"})),
    )
    _EXECUTE_EXCLUDED = True


# Read-only shell commands the tutor may run WITHOUT the human-approval prompt — the trace
# still shows they ran. Kept deliberately tight: navigation/inspection only, no code execution
# (python), no state mutation (sqlite3 can write), no env dump (could leak keys). Anything not
# on this list still requires the learner's explicit approval, so the default is always "ask".
_SAFE_BASH_CMDS = frozenset({
    "pwd", "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "tree", "stat",
    "file", "du", "df", "date", "echo", "printf", "which", "basename", "dirname", "realpath",
    "sort", "uniq", "cut", "nl", "diff", "cmp",
})
# Reject the whole command if it contains any shell metacharacter that could chain, redirect,
# substitute, or escape into something unsafe (so "ls; rm -rf" or "cat $(…)" is never auto-run).
_UNSAFE_BASH = re.compile(r"[;&|<>`$\\]|\n|--?exec|-delete|-fdelete")


def is_safe_bash(command: str) -> bool:
    """True only for a single, simple, read-only command whose first token is whitelisted and
    which has no chaining/redirection/substitution — safe to run without asking the learner."""
    cmd = (command or "").strip()
    if not cmd or _UNSAFE_BASH.search(cmd):
        return False
    return cmd.split()[0] in _SAFE_BASH_CMDS


def pending_bash_approval(agent, config) -> dict | None:
    """If the agent paused for run_bash approval, return {tool, command, explanation}; else None."""
    try:
        interrupts = getattr(agent.get_state(config), "interrupts", None) or ()
    except Exception:
        return None
    if not interrupts:
        return None
    reqs = (interrupts[0].value or {}).get("action_requests") or []
    if not reqs:
        return None
    args = reqs[0].get("args") or {}
    return {"tool": reqs[0].get("name", "run_bash"),
            "command": args.get("command", ""), "explanation": args.get("explanation", "")}


def build_agent(system_prompt: str, tools: list, provider: str | None = None,
                model: str | None = None, checkpointer=None, balance: bool | None = None):
    """Create a deep agent with our tools and prompt, wired to a provider.

    Defaults to the persistent SQLite checkpointer so conversations survive restarts
    and can be listed/resumed from the chats window. Pass `checkpointer` to override
    (e.g. an in-memory one for a throwaway agent).
    """
    from deepagents import create_deep_agent

    _exclude_execute_tool()

    if checkpointer is None:
        from .chatstore import get_checkpointer

        checkpointer = get_checkpointer()

    from .mcp_client import cached_mcp_tools
    from .workspace import build_backend

    # A resilient model: leads with the requested/default provider, then transparently
    # hops to the next configured provider on a transient/provider error, so one
    # provider being down or rate-limited doesn't kill the session. Single-provider
    # setups get a chain of length 1 — identical to before.
    chat = build_fallback_chat_model(provider, model=model, balance=balance, max_tokens=_MAX_TOKENS)
    return create_deep_agent(
        model=chat,
        tools=list(tools) + cached_mcp_tools(),  # + web search / docs, when warmed
        system_prompt=system_prompt,
        backend=build_backend(),  # read-broad host + write-confined /workspace
        checkpointer=checkpointer,
        interrupt_on={"run_bash": {"allowed_decisions": ["approve", "reject"]}},  # human approval
    )
