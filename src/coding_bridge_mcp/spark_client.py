"""Spark API clients for HTTP (OpenAI-compatible) and WebSocket subscriptions."""

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

from coding_bridge_mcp.config import Settings


class SparkApiError(Exception):
    """Raised when the Spark API returns an error."""


class SparkClient(ABC):
    """Abstract client for calling Spark models."""

    @abstractmethod
    async def call(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 1.0,
    ) -> Tuple[str, Dict[str, Any] | None]:
        """Return (assistant_content, usage_dict_or_none)."""
        raise NotImplementedError


class HttpSparkClient(SparkClient):
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

        try:
            async with httpx.AsyncClient(
                timeout=self.settings.timeout_seconds
            ) as client:
                response = await client.post(
                    self.settings.api_url, headers=headers, json=payload
                )
        except httpx.TimeoutException as exc:
            raise SparkApiError("Spark API request timed out") from exc
        except httpx.RequestError as exc:
            raise SparkApiError(f"Spark API request failed: {exc}") from exc

        try:
            data = response.json()
        except Exception as exc:
            raise SparkApiError(
                f"Failed to parse Spark response: {exc}\nBody: {response.text}"
            ) from exc

        if response.status_code != 200:
            detail = data.get("message") if isinstance(data, dict) else None
            if not detail and isinstance(data, dict) and "error" in data:
                detail = data["error"].get("message") if isinstance(data["error"], dict) else str(data["error"])
            raise SparkApiError(
                f"Spark API HTTP {response.status_code}: {detail or response.text or 'unknown error'}"
            )

        # Native Spark wraps its own code/message fields on top of the OpenAI shape.
        code = data.get("code", 0)
        if code != 0:
            raise SparkApiError(
                f"Spark API error {code}: {data.get('message')} (sid={data.get('sid')})"
            )

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise SparkApiError(
                f"Unexpected Spark response structure: {exc}\nBody: {data}"
            ) from exc

        usage = data.get("usage")
        return content, usage


class WebSocketSparkClient(SparkClient):
    """Native WebSocket client (uses AppID + APIKey + APISecret)."""

    # Default endpoints map domain -> wss url. Users can override with SPARK_WS_URL.
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

        content_parts: List[str] = []
        usage: Dict[str, Any] | None = None

        try:
            coro = websockets.connect(auth_url, close_timeout=5)
            ws = await asyncio.wait_for(coro, timeout=15)
        except asyncio.TimeoutError as exc:
            raise SparkApiError("WebSocket connection timed out") from exc
        except Exception as exc:
            raise SparkApiError(f"WebSocket connection failed: {exc}") from exc

        try:
            await ws.send(json.dumps(request))
            async for raw in ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise SparkApiError(f"Invalid WebSocket frame: {raw}") from exc

                header = data.get("header", {})
                code = header.get("code", 0)
                if code != 0:
                    raise SparkApiError(
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
                    break
        except websockets.exceptions.ConnectionClosed as exc:
            # If we already got the final status=2, this is fine.
            if usage is None and not content_parts:
                raise SparkApiError(
                    f"WebSocket closed unexpectedly: {exc}"
                ) from exc
        finally:
            await ws.close()

        return "".join(content_parts), usage


def create_client(settings: Settings) -> SparkClient:
    """Factory: pick the right client for the configured subscription."""
    if settings.mode in {"http", "coding"}:
        return HttpSparkClient(settings)
    if settings.mode == "websocket":
        return WebSocketSparkClient(settings)
    raise ValueError(f"Unsupported SPARK_MODE: {settings.mode}")
