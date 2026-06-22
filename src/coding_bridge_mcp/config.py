"""Configuration and provider detection for Coding Bridge MCP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from coding_bridge_mcp.providers import ProviderProfile, get_provider, resolve_provider_name

VALID_PROXY_MODES = frozenset({"false", "env", "custom"})

# Aliases that are normalized to a canonical mode (case-insensitive).
_TRUE_ALIASES = frozenset({"true", "yes", "on", "1"})
_FALSE_ALIASES = frozenset({"false", "no", "off", "0"})


@dataclass(frozen=True)
class ProxyEndpoint:
    """A single proxy endpoint (scheme-specific)."""

    scheme: str  # "http" or "https"
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None

    def url(self) -> str:
        """Return ``scheme://[user:pass@]host:port`` form for httpx."""
        userinfo = ""
        if self.username:
            from urllib.parse import quote
            userinfo = quote(self.username, safe="")
            if self.password:
                userinfo += f":{quote(self.password, safe='')}"
            userinfo += "@"
        return f"{self.scheme}://{userinfo}{self.host}:{self.port}"


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
    proxy_mode: str  # "false" | "true" | "env" | "custom"
    proxy_http: Optional[ProxyEndpoint]
    proxy_https: Optional[ProxyEndpoint]  # noqa: E501


def _env(keys: str | list[str], default: str = "") -> str:
    """Return the first non-empty value among the given env var names."""
    if isinstance(keys, str):
        keys = [keys]
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


def _parse_proxy_endpoint(scheme: str) -> Optional[ProxyEndpoint]:
    """Parse ``HTTP(S)_PROXY_{HOST,PORT,USER,PASSWORD}`` for the given scheme.

    Returns ``None`` when ``HOST`` is unset; raises ``ValueError`` on partial
    configuration (port without host, or password without user).
    """
    scheme_upper = scheme.upper()
    host = _env(f"{scheme_upper}_PROXY_HOST")
    port_str = _env(f"{scheme_upper}_PROXY_PORT")
    username = _env(f"{scheme_upper}_PROXY_USER")
    password = _env(f"{scheme_upper}_PROXY_PASSWORD")

    if not host and not port_str and not username and not password:
        return None
    if not host or not port_str:
        raise ValueError(
            f"{scheme_upper}_PROXY_HOST and {scheme_upper}_PROXY_PORT "
            "must both be set when configuring a custom proxy"
        )
    try:
        port = int(port_str)
    except ValueError as exc:
        raise ValueError(
            f"{scheme_upper}_PROXY_PORT must be an integer, got {port_str!r}"
        ) from exc
    if not (1 <= port <= 65535):
        raise ValueError(
            f"{scheme_upper}_PROXY_PORT out of range (1-65535): {port}"
        )
    if password and not username:
        raise ValueError(
            f"{scheme_upper}_PROXY_PASSWORD given without {scheme_upper}_PROXY_USER"
        )
    return ProxyEndpoint(
        scheme=scheme,
        host=host,
        port=port,
        username=username or None,
        password=password or None,
    )


def _resolve_proxy_mode() -> str:
    """Resolve ``PROXY`` env var to one of ``VALID_PROXY_MODES``.

    ``true``/``yes``/``on``/``1`` are normalised to ``"env"``;
    ``false``/``no``/``off``/``0`` to ``"false"``. Defaults to ``"false"``.
    """
    raw = _env("PROXY", "false").strip().lower()
    if raw in _TRUE_ALIASES:
        return "env"
    if raw in _FALSE_ALIASES:
        return "false"
    if raw not in VALID_PROXY_MODES:
        accepted = sorted(VALID_PROXY_MODES | _TRUE_ALIASES | _FALSE_ALIASES)
        raise ValueError(
            f"Invalid PROXY value {raw!r}. Expected one of: {accepted}"
        )
    return raw


def _load_proxy_settings() -> tuple[str, Optional[ProxyEndpoint], Optional[ProxyEndpoint]]:
    """Return ``(mode, http_endpoint, https_endpoint)`` per PROXY semantics."""
    mode = _resolve_proxy_mode()
    if mode != "custom":
        return mode, None, None
    http_ep = _parse_proxy_endpoint("http")
    https_ep = _parse_proxy_endpoint("https")
    if http_ep is None and https_ep is None:
        raise ValueError(
            "PROXY=custom requires HTTP_PROXY_HOST/PORT and/or "
            "HTTPS_PROXY_HOST/PORT (both schemes must be configured when used)"
        )
    if http_ep is None or https_ep is None:
        missing = []
        if http_ep is None:
            missing.append("HTTP_PROXY_HOST/PORT")
        if https_ep is None:
            missing.append("HTTPS_PROXY_HOST/PORT")
        raise ValueError(
            "PROXY=custom requires BOTH HTTP and HTTPS proxies: missing "
            + ", ".join(missing)
        )
    return mode, http_ep, https_ep


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

    proxy_mode, proxy_http, proxy_https = _load_proxy_settings()

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
        proxy_mode=proxy_mode,
        proxy_http=proxy_http,
        proxy_https=proxy_https,
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
