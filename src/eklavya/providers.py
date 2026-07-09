"""The model provider layer.

Both GLM (z.ai) and MiniMax expose Anthropic-compatible endpoints, so a single
client speaks to either — we just swap base_url + token + model. Adding Claude
later is trivial (same shape); Gemini/Ollama get thin adapters down the line.

Nothing here hardcodes a secret: tokens come from the environment only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import config  # importing this loads .env, so tokens are available


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    base_url: str
    # Env var names checked in order; first one set wins.
    token_env: tuple[str, ...]
    default_model: str
    models: tuple[str, ...] = field(default_factory=tuple)

    def token(self) -> str | None:
        for name in self.token_env:
            value = os.environ.get(name)
            if value:
                return value
        return None

    def is_configured(self) -> bool:
        return self.token() is not None


PROVIDERS: dict[str, Provider] = {
    "glm": Provider(
        key="glm",
        label="GLM (z.ai)",
        base_url="https://api.z.ai/api/anthropic",
        token_env=("EKLAVYA_GLM_API_KEY", "GLM_API_KEY", "Z_AI_API_KEY"),
        default_model="glm-5.2",
        models=("glm-5.2", "glm-5-turbo", "glm-4.6V"),
    ),
    "minimax": Provider(
        key="minimax",
        label="MiniMax",
        base_url="https://api.minimax.io/anthropic",
        token_env=("EKLAVYA_MINIMAX_API_KEY", "MINIMAX_API_KEY"),
        default_model="MiniMax-M3",
        models=("MiniMax-M3", "MiniMax-M2.7"),
    ),
}


def get_provider(key: str | None = None) -> Provider:
    provider = PROVIDERS.get(key or config.DEFAULT_PROVIDER)
    if provider is None:
        raise KeyError(f"Unknown provider {key!r}. Known: {', '.join(PROVIDERS)}")
    return provider


def configured_providers() -> list[Provider]:
    return [p for p in PROVIDERS.values() if p.is_configured()]


def pick(key: str | None = None) -> Provider:
    """Choose a provider: an explicit key as-is; otherwise the default if it's
    configured, else any configured one (so it just works with a single key set).
    """
    if key:
        return get_provider(key)
    default = get_provider()
    if default.is_configured():
        return default
    others = configured_providers()
    return others[0] if others else default


def build_chat_model(provider_key: str | None = None, model: str | None = None, **kwargs):
    """Build a chat model for a provider.

    GLM and MiniMax both speak the Anthropic API, so one ChatAnthropic client
    handles either — we just point base_url + api_key + model at the right place.
    Because every provider returns the same LangChain interface, switching
    providers mid-conversation is just calling a different model with the same
    message history.
    """
    from langchain_anthropic import ChatAnthropic

    provider = get_provider(provider_key)
    token = provider.token()
    if not token:
        raise RuntimeError(f"{provider.label} is not configured (set {provider.token_env[0]}).")
    return ChatAnthropic(
        model=model or provider.default_model,
        base_url=provider.base_url,
        api_key=token,
        **kwargs,
    )
