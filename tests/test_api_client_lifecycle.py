"""Tests for the shared HTTP client's lifecycle and bounded diagnostics."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coding_bridge_mcp.api_client import ApiError, HttpApiClient
from coding_bridge_mcp.config import Settings


def _settings() -> Settings:
    return Settings(
        provider="xfyun-coding",
        mode="http",
        api_url="https://example.invalid/v2/chat/completions",
        api_password="test-key",
        default_model="astron-code-latest",
        timeout_seconds=30.0,
        max_context_chars=96_000,
        max_messages=40,
        max_tokens=8_192,
        proxy_mode="false",
        proxy_http=None,
        proxy_https=None,
    )


def _response(*, status_code: int = 200, body: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.content = b"{}"
    response.text = "{}"
    response.json.return_value = body or {
        "code": 0,
        "choices": [{"message": {"content": "ok"}}],
    }
    return response


@pytest.mark.asyncio
async def test_http_client_is_reused_and_closed() -> None:
    fake = MagicMock()
    fake.post = AsyncMock(return_value=_response())
    fake.aclose = AsyncMock()

    with patch("coding_bridge_mcp.api_client.httpx.AsyncClient", return_value=fake) as factory:
        client = HttpApiClient(_settings())
        messages = [{"role": "user", "content": "ping"}]
        await client.call(messages, model="astron-code-latest")
        await client.call(messages, model="astron-code-latest")
        await client.aclose()

    factory.assert_called_once()
    assert fake.post.await_count == 2
    fake.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_error_body_is_bounded() -> None:
    fake = MagicMock()
    fake.post = AsyncMock(
        return_value=_response(
            status_code=500,
            body={"error": {"message": "x" * 10_000}},
        )
    )
    fake.aclose = AsyncMock()

    with patch("coding_bridge_mcp.api_client.httpx.AsyncClient", return_value=fake):
        client = HttpApiClient(_settings())
        with pytest.raises(ApiError, match="truncated") as exc_info:
            await client.call(
                [{"role": "user", "content": "ping"}],
                model="astron-code-latest",
            )
        await client.aclose()

    assert len(str(exc_info.value)) < 4500
