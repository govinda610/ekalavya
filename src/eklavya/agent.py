"""Build the deepagents agent that does the teaching.

The agent is the brain (Socratic conversation, judgement); the tools are the
reliable hands (state, ratings, goals). We pass a GLM/MiniMax model instance and
a checkpointer so a conversation persists across turns on one thread_id.
"""

from __future__ import annotations

from .providers import build_chat_model

# A teaching turn can be long (explanations, code); give it room.
_MAX_TOKENS = 4096


def build_agent(system_prompt: str, tools: list, provider: str | None = None,
                model: str | None = None, checkpointer=None):
    """Create a deep agent with our tools and prompt, wired to a provider.

    Defaults to the persistent SQLite checkpointer so conversations survive restarts
    and can be listed/resumed from the chats window. Pass `checkpointer` to override
    (e.g. an in-memory one for a throwaway agent).
    """
    from deepagents import create_deep_agent

    if checkpointer is None:
        from .chatstore import get_checkpointer

        checkpointer = get_checkpointer()

    chat = build_chat_model(provider, model=model, max_tokens=_MAX_TOKENS)
    return create_deep_agent(
        model=chat,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
    )
