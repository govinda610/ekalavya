"""Live smoke test for the provider layer.

Proves three things against the real APIs:
  1. Each configured provider (GLM, MiniMax) answers a prompt.
  2. We can switch providers mid-conversation with a shared message history.

Run:  uv run python scripts/smoke_providers.py
"""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage, HumanMessage

from eklavya.providers import PROVIDERS, build_chat_model, configured_providers


def ping(key: str) -> None:
    provider = PROVIDERS[key]
    model = build_chat_model(key, max_tokens=64)
    start = time.monotonic()
    reply = model.invoke("Reply with exactly: EKLAVYA OK")
    ms = (time.monotonic() - start) * 1000
    print(f"  ✓ {provider.label:12} {provider.default_model:14} {ms:6.0f} ms  →  {reply.text.strip()!r}")


def switch_demo() -> None:
    """Same conversation, two providers — history carries across the switch."""
    print("\nMid-session switch (shared history):")
    history: list = [HumanMessage("My favourite programming language is Rust. Reply 'noted'.")]

    glm = build_chat_model("glm", max_tokens=64)
    r1 = glm.invoke(history)
    history.append(AIMessage(r1.text))
    print(f"  GLM      said: {r1.text.strip()!r}")

    # Switch provider mid-conversation, keeping the exact same history.
    history.append(HumanMessage("Which language did I say was my favourite? One word."))
    minimax = build_chat_model("minimax", max_tokens=64)
    r2 = minimax.invoke(history)
    print(f"  MiniMax  said: {r2.text.strip()!r}")

    if "rust" in r2.text.lower():
        print("  ✓ switch preserved conversation state across providers")
    else:
        print("  ✗ MiniMax did not recall the context — check the switch")


def main() -> None:
    configured = configured_providers()
    if not configured:
        print("No providers configured. Add keys to .env.")
        return
    print("Live provider check:")
    for provider in configured:
        try:
            ping(provider.key)
        except Exception as exc:  # surface the real error, don't hide it
            print(f"  ✗ {provider.label}: {exc}")
    switch_demo()


if __name__ == "__main__":
    main()
