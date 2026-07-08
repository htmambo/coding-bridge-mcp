"""OpenAI-compatible HTTP API client for coding plan services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import httpx

from coding_bridge_mcp.config import Settings
from coding_bridge_mcp.logging_config import get_logger

logger = get_logger(__name__)


def _build_client_kwargs(settings: Settings) -> Dict[str, Any]:
    """Return httpx.AsyncClient kwargs derived from settings.proxy_mode.

    | PROXY      | trust_env | proxy                                  |
    |------------|-----------|----------------------------------------|
    | false (def)| False     | not set (no env injection, no override)|
    | true / env | True      | not set                                |
    | custom     | False     | dict mapping scheme to httpx.Proxy     |

    Centralising this keeps the call() body free of branching logic and gives
    tests a single seam to assert on.
    """
    mode = settings.proxy_mode
    if mode == "custom":
        proxy: Dict[str, httpx.Proxy] = {}
        if settings.proxy_http is not None:
            proxy["http://"] = httpx.Proxy(settings.proxy_http.url())
        if settings.proxy_https is not None:
            proxy["https://"] = httpx.Proxy(settings.proxy_https.url())
        return {
            "timeout": settings.timeout_seconds,
            "trust_env": False,
            "proxy": proxy,
        }
    if mode in {"true", "env"}:
        return {
            "timeout": settings.timeout_seconds,
            "trust_env": True,
        }
    # mode == "false" — default; never honor env, never use proxy override.
    return {
        "timeout": settings.timeout_seconds,
        "trust_env": False,
    }


class ApiError(Exception):
    """Raised when the API returns an error."""


def _safe_url(url: str) -> str:
    """Return scheme+host+path of ``url`` with any credentials/query/fragment stripped.

    Used for logging to avoid leaking credentials that some providers place in
    the URL.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    # IPv6 addresses must be wrapped in brackets.
    if ":" in host:
        host = f"[{host}]"
    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"
    else:
        netloc = host
    return f"{parsed.scheme}://{netloc}{parsed.path or ''}"


def _normalize_usage(usage: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Normalize provider-specific usage dict into a stable schema.

    Returns a dict with these keys (missing values default to 0):

    - ``prompt_tokens``      — input tokens for this turn
    - ``completion_tokens``  — output tokens for this turn
    - ``total_tokens``       — sum of the two
    - ``cached_tokens``      — input tokens served from cache (Anthropic-style)
    - ``cache_creation_input_tokens``  — tokens written to cache this turn
    - ``cache_read_input_tokens``      — tokens read from cache this turn

    Both volcengine-coding and xfyun-coding are OpenAI-compatible. The
    OpenAI/Ark convention is ``usage.prompt_tokens_details.cached_tokens``;
    some providers (notably older xfyun responses) put it at the top level
    as ``cached_tokens``. We accept both shapes and emit the Anthropic-style
    triple so downstream consumers have a stable contract.

    If ``usage`` is ``None`` or empty, returns ``None``.
    """
    if not usage:
        return None

    def _coerce_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    prompt = _coerce_int(usage.get("prompt_tokens"))
    completion = _coerce_int(usage.get("completion_tokens"))
    total = _coerce_int(usage.get("total_tokens")) or (prompt + completion)

    details = usage.get("prompt_tokens_details") or {}
    if isinstance(details, dict):
        cached = _coerce_int(details.get("cached_tokens"))
    else:
        cached = 0
    # Fallback: top-level cached_tokens (some xfyun responses).
    if not cached:
        cached = _coerce_int(usage.get("cached_tokens"))

    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cached_tokens": cached,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


class ApiClient(ABC):
    """Abstract client for calling provider models."""

    @abstractmethod
    async def call(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 1.0,
    ) -> Tuple[str, Dict[str, Any] | None]:
        """Return (assistant_content, usage_dict_or_none)."""
        raise NotImplementedError


class HttpApiClient(ApiClient):
    """OpenAI-compatible HTTP client (uses APIPassword / API key)."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def call(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 1.0,
    ) -> Tuple[str, Dict[str, Any] | None]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": temperature,
            "max_tokens": self.settings.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.api_password}",
            "Content-Type": "application/json",
        }

        safe_url = _safe_url(self.settings.api_url)
        logger.info(
            "http_request",
            url=safe_url,
            model=model,
            message_count=len(messages),
        )
        logger.debug("http_request_payload", model=model, max_tokens=self.settings.max_tokens)

        try:
            # Proxy handling per Settings.proxy_mode; see _build_client_kwargs.
            async with httpx.AsyncClient(**_build_client_kwargs(self.settings)) as client:
                response = await client.post(
                    self.settings.api_url, headers=headers, json=payload
                )
        except httpx.TimeoutException as exc:
            logger.error("http_request_timeout", url=safe_url, model=model)
            raise ApiError("API request timed out") from exc
        except httpx.RequestError as exc:
            logger.error("http_request_failed", url=safe_url, model=model, error=str(exc))
            raise ApiError(f"API request failed: {exc}") from exc

        try:
            data = response.json()
        except Exception as exc:
            raise ApiError(
                f"Failed to parse API response: {exc}\nBody: {response.text}"
            ) from exc

        logger.info("http_response", url=safe_url, model=model, status_code=response.status_code)

        if response.status_code != 200:
            detail = data.get("message") if isinstance(data, dict) else None
            if not detail and isinstance(data, dict) and "error" in data:
                detail = data["error"].get("message") if isinstance(data["error"], dict) else str(data["error"])
            logger.error(
                "http_error_response",
                url=safe_url,
                model=model,
                status_code=response.status_code,
                detail=detail,
            )
            raise ApiError(
                f"API HTTP {response.status_code}: {detail or response.text or 'unknown error'}"
            )

        # Native providers may wrap their own code/message fields on top of the OpenAI shape.
        code = data.get("code", 0)
        if code != 0:
            logger.error(
                "provider_error_code",
                url=safe_url,
                model=model,
                code=code,
                message=data.get("message"),
            )
            raise ApiError(
                f"API error {code}: {data.get('message')} (sid={data.get('sid')})"
            )

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ApiError(
                f"Unexpected API response structure: {exc}\nBody: {data}"
            ) from exc

        # Thinking-mode models (e.g. deepseek-v4-pro) emit the chain-of-thought
        # in ``reasoning_content`` and the final answer in ``content``. A
        # missing/empty ``content`` means the model produced no final answer —
        # surface it explicitly rather than silently returning an empty string
        # (which would let a review tool proceed on empty input).
        if not content:
            # ``choices`` may be missing, None, or an empty list — guard the
            # index so the diagnostic hint itself never raises (which would
            # mask the real "empty content" cause with an IndexError).
            choices = data.get("choices") or [{}]
            msg = (choices[0] or {}).get("message") or {}
            has_reasoning = bool(msg.get("reasoning_content"))
            hint = (
                " (model returned only reasoning_content; the final answer is "
                "empty — retry, raise max_tokens, or switch to a non-thinking model)"
                if has_reasoning
                else ""
            )
            raise ApiError(
                f"API returned empty content{hint}\nBody: {data}"
            )

        usage = _normalize_usage(data.get("usage"))
        return content, usage


def create_client(settings: Settings) -> ApiClient:
    """Factory: return an HTTP client for the configured provider."""
    if settings.mode in {"http", "coding"}:
        return HttpApiClient(settings)
    raise ValueError(f"Unsupported API mode: {settings.mode!r}. Expected 'http'.")
