"""API clients for HTTP (OpenAI-compatible) and WebSocket subscriptions."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any, Dict, List, Tuple
from urllib.parse import urlencode, urlparse

import httpx

from coding_bridge_mcp.config import ProxyEndpoint, Settings
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
    """Return scheme+netloc+path of ``url`` with any query/fragment stripped.

    Used for logging to avoid leaking credentials that some providers place in
    the URL (e.g. signed WebSocket auth URLs).
    """
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path or ''}"


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

        usage = data.get("usage")
        return content, usage


class WebSocketApiClient(ApiClient):
    """Native WebSocket client (uses AppID + APIKey + APISecret)."""

    # Default endpoints map domain -> wss url. Users can override via api_url
    # (populated from the active provider profile's api_url_env_vars).
    DEFAULT_WS_URLS: Dict[str, str] = {
        "4.0Ultra": "wss://spark-api.xf-yun.com/v4.0/chat",
        "generalv3.5": "wss://spark-api.xf-yun.com/v3.5/chat",
        "max-32k": "wss://spark-api.xf-yun.com/v3.5/chat",
        "generalv3": "wss://spark-api.xf-yun.com/v3.1/chat",
        "pro-128k": "wss://spark-api.xf-yun.com/v3.1/chat",
        "lite": "wss://spark-api.xf-yun.com/v1.1/chat",
        "kjwx": "wss://spark-api.xf-yun.com/v1.1/chat",
    }

    DEFAULT_MAX_TOKENS: Dict[str, int] = {
        "4.0Ultra": 32768,
        "generalv3.5": 4096,
        "max-32k": 32768,
        "generalv3": 4096,
        "pro-128k": 4096,
        "lite": 4096,
        "kjwx": 4096,
    }

    def __init__(self, settings: Settings):
        self.settings = settings
        try:
            import websockets  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "WebSocket mode requires the 'websockets' package. "
                "Install it with: uv add websockets"
            ) from exc

    def _ws_url(self, model: str) -> str:
        if self.settings.api_url:
            return self.settings.api_url
        return self.DEFAULT_WS_URLS.get(model, "wss://spark-api.xf-yun.com/v4.0/chat")

    def _build_auth_url(self, url: str) -> str:
        parsed = urlparse(url)
        host = parsed.netloc
        path = parsed.path or "/"
        date = format_datetime(datetime.now(timezone.utc), usegmt=True)

        signature_origin = f"host: {host}\ndate: {date}\nGET {path} HTTP/1.1"
        signature = base64.b64encode(
            hmac.new(
                self.settings.api_secret.encode("utf-8"),
                signature_origin.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")

        authorization_origin = (
            f'api_key="{self.settings.api_key}", '
            f'algorithm="hmac-sha256", '
            f'headers="host date request-line", '
            f'signature="{signature}"'
        )
        authorization = base64.b64encode(
            authorization_origin.encode("utf-8")
        ).decode("utf-8")

        params = {"authorization": authorization, "date": date, "host": host}
        return f"{url}?{urlencode(params)}"

    def _build_request(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
    ) -> Dict[str, Any]:
        # WebSocket protocol uses 0..1 temperature range and different defaults.
        ws_temperature = max(0.01, min(1.0, temperature))
        return {
            "header": {"app_id": self.settings.app_id, "uid": "coding_bridge_mcp"},
            "parameter": {
                "chat": {
                    "domain": model,
                    "temperature": ws_temperature,
                    "max_tokens": self.DEFAULT_MAX_TOKENS.get(model, 4096),
                    "top_k": 4,
                }
            },
            "payload": {"message": {"text": messages}},
        }

    async def call(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 1.0,
    ) -> Tuple[str, Dict[str, Any] | None]:
        import websockets

        url = self._ws_url(model)
        auth_url = self._build_auth_url(url)
        request = self._build_request(messages, model, temperature)

        safe_url = _safe_url(url)
        logger.info("websocket_request", url=safe_url, model=model, message_count=len(messages))

        content_parts: List[str] = []
        usage: Dict[str, Any] | None = None

        try:
            connect_kwargs: Dict[str, Any] = {"close_timeout": 5}
            # websockets lib reads ``https_proxy`` from env when ``proxy=None``;
            # pass an explicit value to make intent unambiguous.
            if self.settings.proxy_mode == "custom" and self.settings.proxy_https is not None:
                connect_kwargs["proxy"] = self.settings.proxy_https.url()
            elif self.settings.proxy_mode in {"true", "env"}:
                # Honor env: websockets >=12 reads ``https_proxy`` automatically
                # when ``proxy`` is not explicitly set. Leave it absent to opt in.
                pass
            # mode == "false": websockets still defaults to honoring ``https_proxy``
            # env var. The library does not expose a single ``trust_env`` knob
            # like httpx, so we must scrub the env for this call when mode=false.
            if self.settings.proxy_mode == "false":
                connect_kwargs["proxy"] = None
            coro = websockets.connect(auth_url, **connect_kwargs)
            ws = await asyncio.wait_for(coro, timeout=15)
        except asyncio.TimeoutError as exc:
            logger.error("websocket_connection_timeout", url=safe_url, model=model)
            raise ApiError("WebSocket connection timed out") from exc
        except Exception as exc:
            # NOTE: do not log `exc` directly; the underlying `websockets`
            # library embeds the full URL (including the signed `auth_url`) in
            # its exception message. Log only the exception class name.
            logger.error(
                "websocket_connection_failed",
                url=safe_url,
                model=model,
                exc_type=type(exc).__name__,
            )
            raise ApiError(f"WebSocket connection failed: {type(exc).__name__}") from exc

        try:
            await ws.send(json.dumps(request))
            async for raw in ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ApiError(f"Invalid WebSocket frame: {raw}") from exc

                header = data.get("header", {})
                code = header.get("code", 0)
                if code != 0:
                    logger.error(
                        "websocket_error_frame",
                        url=safe_url,
                        model=model,
                        code=code,
                        message=header.get("message"),
                    )
                    raise ApiError(
                        f"WebSocket error {code}: {header.get('message')} "
                        f"(sid={header.get('sid')})"
                    )

                choices = data.get("payload", {}).get("choices", {})
                for text_item in choices.get("text", []):
                    part = text_item.get("content")
                    if part:
                        content_parts.append(part)

                status = choices.get("status")
                if status == 2:
                    usage = data.get("payload", {}).get("usage")
                    logger.info(
                        "websocket_response_complete",
                        url=safe_url,
                        model=model,
                        has_usage=usage is not None,
                    )
                    break
        except websockets.exceptions.ConnectionClosed as exc:
            # If we already got the final status=2, this is fine.
            if usage is None and not content_parts:
                logger.error(
                    "websocket_closed_unexpectedly",
                    url=safe_url,
                    model=model,
                    exc_type=type(exc).__name__,
                )
                raise ApiError(
                    f"WebSocket closed unexpectedly: {type(exc).__name__}"
                ) from exc
        finally:
            await ws.close()

        return "".join(content_parts), usage


def create_client(settings: Settings) -> ApiClient:
    """Factory: pick the right client for the configured subscription."""
    if settings.mode in {"http", "coding"}:
        return HttpApiClient(settings)
    if settings.mode == "websocket":
        return WebSocketApiClient(settings)
    raise ValueError(f"Unsupported API mode: {settings.mode!r}. Expected 'http' or 'websocket'.")
