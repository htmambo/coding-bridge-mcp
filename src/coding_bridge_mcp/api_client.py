"""OpenAI-compatible HTTP API client for coding plan services."""

from __future__ import annotations

import asyncio
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import httpx

from coding_bridge_mcp.config import Settings
from coding_bridge_mcp.logging_config import get_logger

logger = get_logger(__name__)

_MAX_ERROR_BODY_CHARS = 4096


def _build_client_kwargs(settings: Settings) -> Dict[str, Any]:
    """Return httpx.AsyncClient kwargs derived from settings.proxy_mode.

    | PROXY      | trust_env | proxy transport                         |
    |------------|-----------|------------------------------------------|
    | false (def)| False     | not set (no env injection, no override)  |
    | true / env | True      | not set                                  |
    | custom     | False     | scheme-specific AsyncHTTPTransport mounts|

    Centralising this keeps the call() body free of branching logic and gives
    tests a single seam to assert on. ``httpx>=0.28`` accepts one ``proxy``
    value, so custom HTTP/HTTPS endpoints use transport mounts instead of a
    mapping passed to the removed ``proxy`` parameter.
    """
    timeout = httpx.Timeout(
        timeout=settings.timeout_seconds,
        connect=settings.connect_timeout_seconds,
        read=settings.timeout_seconds,
        write=settings.write_timeout_seconds,
        pool=settings.pool_timeout_seconds,
    )
    limits = httpx.Limits(
        max_connections=settings.max_connections,
        max_keepalive_connections=settings.max_keepalive_connections,
    )
    common: Dict[str, Any] = {"timeout": timeout, "limits": limits}

    mode = settings.proxy_mode
    if mode == "custom":
        mounts: Dict[str, httpx.AsyncBaseTransport] = {}
        if settings.proxy_http is not None:
            mounts["http://"] = httpx.AsyncHTTPTransport(
                proxy=settings.proxy_http.url()
            )
        if settings.proxy_https is not None:
            mounts["https://"] = httpx.AsyncHTTPTransport(
                proxy=settings.proxy_https.url()
            )
        return {**common, "trust_env": False, "mounts": mounts}
    if mode in {"true", "env"}:
        return {**common, "trust_env": True}
    # mode == "false" — default; never honor env, never use proxy override.
    return {**common, "trust_env": False}


class ApiError(Exception):
    """Raised when the API returns an error.

    ``retryable`` tells the retry loop whether another attempt is worthwhile;
    ``retry_after`` carries the server-provided delay hint (seconds) when the
    response included a parseable ``Retry-After`` header.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


# Keywords in error responses that indicate a retryable rate-limit / throttling
# condition, even when the HTTP status code is not 429 (e.g. qianfan returns 200
# with a provider-level error on burst protection).
#
# Note: this list is intentionally narrower than "quota exceeded" alone —
# providers (notably sensenova) return 4xx messages like "Workspace allocated
# quota exceeded" for HARD configuration limits (max_tokens wall, etc.) that
# the client must NOT retry. The override list below takes precedence and is
# the single source of truth for "hard error, do not retry". See
# ``_NON_RETRYABLE_OVERRIDE_KEYWORDS`` and ``_first_override_keyword``.
_RETRYABLE_RATE_LIMIT_HINTS = (
    "request burst",
    "rate limit",
    "rate-limit",
    "too many requests",
    "system protection",
    "系统保护",
    "限流",
    "throttl",
)

# Defensive override: body keywords that indicate a non-transient
# configuration / billing / hard-limit error. When present, the response must
# NOT be treated as a retryable rate-limit regardless of HTTP status.
# Tested explicitly in ``tests/test_api_client_retry.py``.
_NON_RETRYABLE_OVERRIDE_KEYWORDS = (
    "workspace allocated quota",
    "workspace quota",
    "insufficient balance",
    "insufficient credits",
    "余额不足",
    "欠费",
    "payment required",
    "subscription expired",
    "billing limit",
    "plan limit",
)


def _is_retryable_status(status_code: int) -> bool:
    """Return True for HTTP status codes we should retry on."""
    if status_code == 429:
        return True
    if 500 <= status_code < 600:
        return True
    return False


def _flatten_body_text(body: Any) -> str:
    """Return a lowercased flattened string of all string values in ``body``.

    Walks dicts and lists up to depth 3 so nested error objects like
    ``{"error": {"message": "..."}}`` are covered. The single string input
    case is the fast path. Any other shape falls back to ``repr()``.
    """
    if isinstance(body, str):
        return body.lower()
    if isinstance(body, dict):
        parts: list[str] = []

        def _walk(obj: Any, depth: int = 0) -> None:
            if depth > 3:
                return
            if isinstance(obj, str):
                parts.append(obj)
            elif isinstance(obj, dict):
                for v in obj.values():
                    _walk(v, depth + 1)
            elif isinstance(obj, list):
                for v in obj:
                    _walk(v, depth + 1)

        _walk(body)
        return " ".join(parts).lower()
    return str(body).lower()


def _first_override_keyword(body: Any) -> str | None:
    """Return the first ``_NON_RETRYABLE_OVERRIDE_KEYWORDS`` that matches ``body``,
    or ``None`` if none match. Used for diagnostic logging when the override
    short-circuits the retry decision in ``_request_once``.
    """
    text = _flatten_body_text(body)
    for kw in _NON_RETRYABLE_OVERRIDE_KEYWORDS:
        if kw in text:
            return kw
    return None


def _body_hints_rate_limit(body: Any) -> bool:
    """Heuristic: does the response body mention a transient rate-limit / throttling
    condition that warrants retry?

    Two-step logic:
      1. If any ``_NON_RETRYABLE_OVERRIDE_KEYWORDS`` matches, return ``False``
         — hard configuration / billing errors must never look like rate limits.
      2. Otherwise, scan for ``_RETRYABLE_RATE_LIMIT_HINTS``.

    Robust against varying field names across providers (``message``,
    ``error_msg``, ``msg``, ``error.message``, etc.) without needing an
    exhaustive schema list. Case-insensitive substring match tolerates
    variations like ``"Workspace Allocated Quota"`` or ``"workspace  allocated  quota"``.
    """
    text = _flatten_body_text(body)
    if any(kw in text for kw in _NON_RETRYABLE_OVERRIDE_KEYWORDS):
        return False
    return any(kw in text for kw in _RETRYABLE_RATE_LIMIT_HINTS)


def _extract_retry_after(headers: Dict[str, Any]) -> float | None:
    """Parse Retry-After header (delay-seconds or HTTP-date) into seconds.

    Returns None when the header is absent or unparseable.
    """
    raw = headers.get("retry-after")
    if raw is None:
        # httpx lowercases header names by default; try original-case just in case.
        raw = headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    # HTTP-date form (RFC 7231 §7.1.3), e.g. "Wed, 21 Oct 2015 07:28:00 GMT".
    # Best-effort: any parse failure is treated the same as a missing header.
    try:
        retry_at = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at is None:  # defensive; parsedate_to_datetime raises on 3.10+
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())


def _compute_backoff_delay(
    attempt: int,
    base_delay: float,
    max_delay: float = 30.0,
    retry_after: float | None = None,
) -> float:
    """Compute exponential backoff delay for the given (0-based) attempt.

    ``attempt`` is 0 for the first retry.  Delay grows as
    ``base_delay * 2^attempt`` capped at ``max_delay``, plus ±20% jitter.
    When ``retry_after`` is provided and is larger, it wins (never wait less
    than the server asked).
    """
    exponential = min(base_delay * (2**attempt), max_delay)
    # ±20% jitter
    jitter = exponential * random.uniform(-0.2, 0.2)
    delay = exponential + jitter
    if retry_after is not None and retry_after > delay:
        delay = retry_after
    return max(0.0, delay)


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


def _bounded_text(value: Any, limit: int = _MAX_ERROR_BODY_CHARS) -> str:
    """Return a bounded diagnostic string suitable for errors and logs."""
    text = value if isinstance(value, str) else repr(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


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

    async def aclose(self) -> None:
        """Release client resources. Stateless test clients may keep the default no-op."""


class HttpApiClient(ApiClient):
    """OpenAI-compatible HTTP client (uses APIPassword / API key)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._http_client: httpx.AsyncClient | None = None
        self._http_client_lock = asyncio.Lock()

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is not None:
            return self._http_client
        async with self._http_client_lock:
            if self._http_client is None:
                self._http_client = httpx.AsyncClient(
                    **_build_client_kwargs(self.settings)
                )
            return self._http_client

    async def aclose(self) -> None:
        async with self._http_client_lock:
            client = self._http_client
            self._http_client = None
        if client is not None:
            await client.aclose()

    async def call(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 1.0,
    ) -> Tuple[str, Dict[str, Any] | None]:
        max_retries = self.settings.max_retries
        base_delay = self.settings.retry_base_delay

        last_exc: BaseException | None = None
        for attempt in range(max_retries + 1):
            try:
                return await self._request_once(messages, model, temperature)
            except ApiError as exc:
                last_exc = exc
                if attempt >= max_retries:
                    raise
                # Decide if this error is worth retrying.
                if not exc.retryable:
                    raise
                delay = _compute_backoff_delay(
                    attempt, base_delay, retry_after=exc.retry_after
                )
                safe_url = _safe_url(self.settings.api_url)
                logger.warning(
                    "http_retry",
                    url=safe_url,
                    model=model,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay_seconds=round(delay, 3),
                    reason=_bounded_text(str(exc), 200),
                )
                await asyncio.sleep(delay)
        # Should be unreachable — loop either returns or raises.
        if last_exc is not None:
            raise last_exc
        raise ApiError("request failed for an unknown reason")

    async def _request_once(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
    ) -> Tuple[str, Dict[str, Any] | None]:
        """Perform a single HTTP request attempt.

        Raises ``ApiError`` on failure; ``ApiError.retryable`` tells the caller
        whether retrying makes sense.
        """
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
            request_chars=sum(len(message.get("content", "")) for message in messages),
        )
        logger.debug("http_request_payload", model=model, max_tokens=self.settings.max_tokens)

        started_at = time.perf_counter()
        try:
            client = await self._get_http_client()
            response = await client.post(
                self.settings.api_url, headers=headers, json=payload
            )
        except httpx.TimeoutException as exc:
            logger.error(
                "http_request_timeout",
                url=safe_url,
                model=model,
                elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
            )
            raise ApiError("API request timed out", retryable=True) from exc
        except httpx.RequestError as exc:
            logger.error(
                "http_request_failed",
                url=safe_url,
                model=model,
                error=_bounded_text(str(exc)),
                elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
            )
            raise ApiError(f"API request failed: {exc}", retryable=True) from exc

        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)

        try:
            data = response.json()
        except Exception as exc:
            raise ApiError(
                f"Failed to parse API response: {exc}\nBody: {_bounded_text(response.text)}"
            ) from exc

        logger.info(
            "http_response",
            url=safe_url,
            model=model,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            response_bytes=len(response.content),
        )

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
            # Step 1: hard configuration / billing errors must NEVER retry,
            # even when status is 429 / 5xx (e.g. sensenova's "Workspace
            # allocated quota exceeded" returns 429 but is a max_tokens wall).
            override_match = _first_override_keyword(data)
            if override_match is not None:
                logger.warning(
                    "non_retryable_override",
                    url=safe_url,
                    model=model,
                    status_code=response.status_code,
                    matched_keyword=override_match,
                )
                retryable = False
            else:
                # Retryable on 429 / 5xx, or when the body hints at rate limiting.
                retryable = _is_retryable_status(response.status_code) or _body_hints_rate_limit(data)
            raise ApiError(
                f"API HTTP {response.status_code}: "
                f"{_bounded_text(detail or response.text or 'unknown error')}",
                retryable=retryable,
                retry_after=_extract_retry_after(dict(response.headers)) if retryable else None,
            )

        # Native providers may wrap their own code/message fields on top of the OpenAI shape.
        code = data.get("code", 0)
        if code != 0:
            logger.error(
                "provider_error_code",
                url=safe_url,
                model=model,
                code=code,
                error_message=data.get("message"),
            )
            # Step 1: override takes precedence — hard configuration / billing
            # errors must not be retried even when the provider wraps them in
            # a code field.
            override_match = _first_override_keyword(data)
            if override_match is not None:
                logger.warning(
                    "non_retryable_override",
                    url=safe_url,
                    model=model,
                    code=code,
                    matched_keyword=override_match,
                )
                retryable = False
            else:
                # Provider-level errors are retryable when the message hints at
                # rate limiting / burst protection (e.g. qianfan's "System protection
                # triggered by request burst").
                retryable = _body_hints_rate_limit(data)
            raise ApiError(
                f"API error {code}: {data.get('message')} (sid={data.get('sid')})",
                retryable=retryable,
            )

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ApiError(
                f"Unexpected API response structure: {exc}\nBody: {_bounded_text(data)}"
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
            # Empty content is usually a max_tokens issue, not a transient
            # error, so ``retryable`` stays False.
            raise ApiError(
                f"API returned empty content{hint}\nBody: {_bounded_text(data)}"
            )

        usage = _normalize_usage(data.get("usage"))
        return content, usage


def create_client(settings: Settings) -> ApiClient:
    """Factory: return an HTTP client for the configured provider."""
    if settings.mode == "http":
        return HttpApiClient(settings)
    raise ValueError(f"Unsupported API mode: {settings.mode!r}. Expected 'http'.")
