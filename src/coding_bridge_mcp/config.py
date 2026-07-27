"""Configuration and provider detection for Coding Bridge MCP."""

from __future__ import annotations

import os
import math
from dataclasses import dataclass
from typing import Optional

from coding_bridge_mcp.providers import get_provider, resolve_provider_name

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
    mode: str  # "http" (保留字段以备未来协议扩展)
    api_url: str  # HTTP endpoint (full /chat/completions URL)
    api_password: str  # HTTP Bearer token / API key
    default_model: str
    timeout_seconds: float
    max_context_chars: int
    max_messages: int
    max_tokens: int
    proxy_mode: str  # "false" | "true" | "env" | "custom"
    proxy_http: Optional[ProxyEndpoint]
    proxy_https: Optional[ProxyEndpoint]  # noqa: E501
    max_connections: int = 20
    max_keepalive_connections: int = 10
    connect_timeout_seconds: float = 10.0
    write_timeout_seconds: float = 300.0
    pool_timeout_seconds: float = 10.0
    session_ttl_seconds: float = 3600.0
    max_sessions: int = 1000
    max_message_chars: int = 1_048_576
    max_history_response_chars: int = 262_144
    max_retries: int = 3
    retry_base_delay: float = 1.0


def _env(keys: str | list[str], default: str = "") -> str:
    """Return the first non-empty value among the given env var names."""
    if isinstance(keys, str):
        keys = [keys]
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


def _env_int(keys: str | list[str], default: int) -> int:
    """Parse a required integer environment value with a useful error."""
    raw = _env(keys, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{keys!r} must be an integer, got {raw!r}") from exc


def _env_float(keys: str | list[str], default: float) -> float:
    """Parse a finite floating-point environment value with a useful error."""
    raw = _env(keys, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{keys!r} must be a number, got {raw!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"{keys!r} must be finite, got {raw!r}")
    return value


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
    timeout_seconds = _env_float(["MCP_TIMEOUT_SECONDS", "SPARK_TIMEOUT_SECONDS"], 300.0)
    max_context_chars = _env_int(
        ["MCP_MAX_CONTEXT_CHARS", "SPARK_MAX_CONTEXT_CHARS"],
        profile.default_max_context_chars,
    )
    max_messages = _env_int(["MCP_MAX_MESSAGES", "SPARK_MAX_MESSAGES"], 40)
    max_tokens = _env_int(["MCP_MAX_TOKENS", "SPARK_MAX_TOKENS"], profile.default_max_tokens)

    max_connections = _env_int("MCP_MAX_CONNECTIONS", 20)
    max_keepalive_connections = _env_int("MCP_MAX_KEEPALIVE_CONNECTIONS", 10)
    connect_timeout_seconds = _env_float("MCP_CONNECT_TIMEOUT_SECONDS", 10.0)
    write_timeout_seconds = _env_float("MCP_WRITE_TIMEOUT_SECONDS", timeout_seconds)
    pool_timeout_seconds = _env_float("MCP_POOL_TIMEOUT_SECONDS", 10.0)
    session_ttl_seconds = _env_float("MCP_SESSION_TTL_SECONDS", 3600.0)
    max_sessions = _env_int("MCP_MAX_SESSIONS", 1000)
    max_message_chars = _env_int("MCP_MAX_MESSAGE_CHARS", max_context_chars)
    max_history_response_chars = _env_int("MCP_MAX_HISTORY_RESPONSE_CHARS", 262_144)
    max_retries = _env_int("MCP_MAX_RETRIES", 3)
    retry_base_delay = _env_float("MCP_RETRY_BASE_DELAY", 1.0)

    api_url = _env(profile.api_url_env_vars, profile.default_api_url)
    default_model = _env(profile.model_env_vars, profile.default_model)
    api_password = _env(profile.api_key_env_vars, "")

    proxy_mode, proxy_http, proxy_https = _load_proxy_settings()

    return Settings(
        provider=provider_name,
        mode=profile.mode,
        api_url=api_url,
        api_password=api_password,
        default_model=default_model,
        timeout_seconds=timeout_seconds,
        max_context_chars=max_context_chars,
        max_messages=max_messages,
        max_tokens=max_tokens,
        proxy_mode=proxy_mode,
        proxy_http=proxy_http,
        proxy_https=proxy_https,
        max_connections=max_connections,
        max_keepalive_connections=max_keepalive_connections,
        connect_timeout_seconds=connect_timeout_seconds,
        write_timeout_seconds=write_timeout_seconds,
        pool_timeout_seconds=pool_timeout_seconds,
        session_ttl_seconds=session_ttl_seconds,
        max_sessions=max_sessions,
        max_message_chars=max_message_chars,
        max_history_response_chars=max_history_response_chars,
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
    )


def validate_settings(settings: Settings) -> None:
    """Raise a clear error if the selected provider is mis-configured."""
    profile = get_provider(settings.provider)

    positive_ints = {
        "max_context_chars": settings.max_context_chars,
        "max_messages": settings.max_messages,
        "max_tokens": settings.max_tokens,
        "max_connections": settings.max_connections,
        "max_keepalive_connections": settings.max_keepalive_connections,
        "max_sessions": settings.max_sessions,
        "max_message_chars": settings.max_message_chars,
        "max_history_response_chars": settings.max_history_response_chars,
    }
    for name, value in positive_ints.items():
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero, got {value}")

    if settings.max_retries < 0:
        raise ValueError(f"max_retries must be non-negative, got {settings.max_retries}")
    if not math.isfinite(settings.retry_base_delay) or settings.retry_base_delay <= 0:
        raise ValueError(
            f"retry_base_delay must be finite and greater than zero, "
            f"got {settings.retry_base_delay}"
        )

    finite_positive = {
        "timeout_seconds": settings.timeout_seconds,
        "connect_timeout_seconds": settings.connect_timeout_seconds,
        "write_timeout_seconds": settings.write_timeout_seconds,
        "pool_timeout_seconds": settings.pool_timeout_seconds,
        "session_ttl_seconds": settings.session_ttl_seconds,
    }
    for name, value in finite_positive.items():
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and greater than zero, got {value}")
    if settings.max_keepalive_connections > settings.max_connections:
        raise ValueError(
            "max_keepalive_connections cannot exceed max_connections: "
            f"{settings.max_keepalive_connections} > {settings.max_connections}"
        )

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
