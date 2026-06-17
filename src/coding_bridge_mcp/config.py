"""Configuration and provider detection for Coding Bridge MCP."""

from __future__ import annotations

import os
from dataclasses import dataclass

from coding_bridge_mcp.providers import ProviderProfile, get_provider, resolve_provider_name


@dataclass(frozen=True)
class Settings:
    """Runtime configuration parsed from environment variables."""

    provider: str
    mode: str  # "http" or "websocket"
    api_url: str  # HTTP endpoint (full /chat/completions URL) or WS URL
    api_password: str  # HTTP Bearer token / API key
    app_id: str  # WebSocket app id
    api_key: str  # WebSocket API key (signature)
    api_secret: str  # WebSocket API secret
    default_model: str
    timeout_seconds: float
    max_context_chars: int
    max_messages: int
    max_tokens: int


def _env(keys: str | list[str], default: str = "") -> str:
    """Return the first non-empty value among the given env var names."""
    if isinstance(keys, str):
        keys = [keys]
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


def load_settings() -> Settings:
    """Load settings from environment variables."""
    provider_name = resolve_provider_name()
    profile = get_provider(provider_name)

    # Generic tunables, with legacy SPARK_* fallbacks for backward compatibility.
    timeout_seconds = float(_env(["MCP_TIMEOUT_SECONDS", "SPARK_TIMEOUT_SECONDS"], "120"))
    max_context_chars = int(
        _env(
            ["MCP_MAX_CONTEXT_CHARS", "SPARK_MAX_CONTEXT_CHARS"],
            str(profile.default_max_context_chars),
        )
    )
    max_messages = int(_env(["MCP_MAX_MESSAGES", "SPARK_MAX_MESSAGES"], "40"))
    max_tokens = int(
        _env(["MCP_MAX_TOKENS", "SPARK_MAX_TOKENS"], str(profile.default_max_tokens))
    )

    api_url = _env(profile.api_url_env_vars, profile.default_api_url)
    default_model = _env(profile.model_env_vars, profile.default_model)
    api_password = _env(profile.api_key_env_vars, "")

    return Settings(
        provider=provider_name,
        mode=profile.mode,
        api_url=api_url,
        api_password=api_password,
        app_id=_env("SPARK_APP_ID", ""),
        api_key=_env(["SPARK_API_KEY", "API_KEY"], ""),
        api_secret=_env("SPARK_API_SECRET", ""),
        default_model=default_model,
        timeout_seconds=timeout_seconds,
        max_context_chars=max_context_chars,
        max_messages=max_messages,
        max_tokens=max_tokens,
    )


def validate_settings(settings: Settings) -> None:
    """Raise a clear error if the selected provider is mis-configured."""
    profile = get_provider(settings.provider)

    if profile.mode == "http":
        if not settings.api_password:
            raise RuntimeError(
                f"Provider '{settings.provider}' requires one of: "
                + ", ".join(profile.api_key_env_vars)
            )
        if not settings.api_url:
            raise RuntimeError(
                f"Provider '{settings.provider}' requires one of: "
                + ", ".join(profile.api_url_env_vars)
            )
    elif profile.mode == "websocket":
        missing = [
            name
            for name, value in {
                "SPARK_APP_ID": settings.app_id,
                "SPARK_API_KEY": settings.api_key,
                "SPARK_API_SECRET": settings.api_secret,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                "WebSocket provider requires all of: " + ", ".join(missing)
            )
