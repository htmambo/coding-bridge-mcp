"""Contract tests for the sensenova provider.

These tests pin down the protocol-level contract between HttpApiClient and the
SenseNova (商汤日日新) Token Plan endpoint — they do **not** perform real
network calls. They mirror test_qianfan_contracts.py because sensenova is added
without a live key, so the wire shape is locked here from the published docs
(https://platform.sensenova.cn/docs).

What we lock down here:

1. Settings layer: PROVIDER=sensenova resolves to the documented endpoint /
   model / credential fallback chain.
2. HTTP layer: HttpApiClient.call posts to the documented URL, sends
   ``Authorization: Bearer <key>``, includes the expected payload fields, and
   returns the assistant content from the standard OpenAI shape.
3. Error path: SenseNova's ``{"error": {"message": ...}}`` body on a non-200
   response is surfaced as ApiError with the upstream message, not swallowed.
4. Usage path: a 200 response's ``usage`` block (with the OpenAI-style
   ``prompt_tokens_details.cached_tokens``) flows through _normalize_usage into
   the Anthropic-style schema our get_token_stats tool consumes.
"""

from __future__ import annotations

import asyncio
import json
import os
from importlib import reload
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coding_bridge_mcp import api_client as api_client_module
from coding_bridge_mcp import config as config_module
from coding_bridge_mcp.config import Settings

# Re-resolve ApiError / HttpApiClient via ``api_client_module`` inside each
# test that needs to compare exception types. A top-level ``from ... import
# ApiError`` would bind a stale class object and break identity checks
# after ``test_config.test_client_factory`` reloads api_client_module.
HttpApiClient = api_client_module.HttpApiClient


# ---------------------------------------------------------------------------
# Settings layer
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "PROVIDER", "SPARK_MODE",
        "API_KEY", "SPARK_API_PASSWORD", "SPARK_API_KEY",
        "SENSENOVA_API_KEY", "SENSENOVA_API_URL", "SENSENOVA_MODEL",
        "MCP_MAX_CONTEXT_CHARS", "MCP_MAX_TOKENS",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_sensenova_provider_profile_loaded() -> None:
    """The SENSENOVA profile is registered and matches the documented contract."""
    from coding_bridge_mcp import providers

    assert "sensenova" in providers.PROVIDERS
    profile = providers.get_provider("sensenova")
    assert profile.mode == "http"
    assert profile.default_api_url == "https://token.sensenova.cn/v1/chat/completions"
    assert profile.default_model == "deepseek-v4-flash"
    assert profile.api_key_env_vars == ["API_KEY", "SENSENOVA_API_KEY"]
    assert profile.api_url_env_vars == ["SENSENOVA_API_URL"]
    assert profile.model_env_vars == ["SENSENOVA_MODEL"]


def test_sensenova_settings_resolve() -> None:
    os.environ["PROVIDER"] = "sensenova"
    os.environ["API_KEY"] = "sensenova-test-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "sensenova"
    assert settings.api_url == "https://token.sensenova.cn/v1/chat/completions"
    assert settings.default_model == "deepseek-v4-flash"
    assert settings.api_password == "sensenova-test-key"


def test_sensenova_url_and_model_override_takes_effect() -> None:
    os.environ["PROVIDER"] = "sensenova"
    os.environ["SENSENOVA_API_KEY"] = "k"
    os.environ["SENSENOVA_API_URL"] = "https://sensenova-staging.example.com/v1/chat/completions"
    os.environ["SENSENOVA_MODEL"] = "sensenova-6.7-flash-lite"
    reload(config_module)
    settings = config_module.load_settings()

    assert settings.api_url == "https://sensenova-staging.example.com/v1/chat/completions"
    assert settings.default_model == "sensenova-6.7-flash-lite"


def test_sensenova_missing_key_raises() -> None:
    os.environ["PROVIDER"] = "sensenova"
    reload(config_module)
    settings = config_module.load_settings()
    with pytest.raises(RuntimeError, match="SENSENOVA_API_KEY"):
        config_module.validate_settings(settings)


# ---------------------------------------------------------------------------
# HTTP layer — wire-shape contract with mocked httpx
# ---------------------------------------------------------------------------


def _sensenova_settings() -> Settings:
    return Settings(
        provider="sensenova",
        mode="http",
        api_url="https://token.sensenova.cn/v1/chat/completions",
        api_password="sensenova-test-key",
        default_model="sensenova-6.7-flash-lite",
        timeout_seconds=30.0,
        max_context_chars=96_000,
        max_messages=40,
        max_tokens=8_192,
        proxy_mode="false",
        proxy_http=None,
        proxy_https=None,
    )


def _spy_async_client(
    captured: dict,
    *,
    status_code: int = 200,
    body: dict | None = None,
) -> MagicMock:
    """Patch httpx.AsyncClient; record the post() call kwargs in ``captured``."""
    response_body = body if body is not None else {
        "choices": [{"message": {"content": "ok"}}],
    }

    def _spy(*args, **kwargs):
        captured["ctor_args"] = args
        captured["ctor_kwargs"] = dict(kwargs)
        fake = MagicMock()
        fake.__aenter__ = AsyncMock(return_value=fake)
        fake.__aexit__ = AsyncMock(return_value=None)

        post_response = MagicMock()
        post_response.status_code = status_code
        post_response.json.return_value = response_body
        # Mirror a real HTTP response body — JSON-serialised, not str(dict).
        post_response.text = json.dumps(response_body, ensure_ascii=False)

        async def _post(*p_args, **p_kwargs):
            captured["post_url"] = p_args[0] if p_args else p_kwargs.get("url")
            captured["post_headers"] = p_kwargs.get("headers", {})
            captured["post_payload"] = p_kwargs.get("json")
            return post_response

        fake.post = _post
        return fake

    return patch("httpx.AsyncClient", side_effect=_spy)


def test_sensenova_posts_to_documented_endpoint() -> None:
    """POST URL is exactly the SenseNova Token Plan chat endpoint."""
    captured: dict = {}
    with _spy_async_client(captured):
        asyncio.run(HttpApiClient(_sensenova_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="sensenova-6.7-flash-lite",
        ))
    assert captured["post_url"] == "https://token.sensenova.cn/v1/chat/completions"


def test_sensenova_sends_bearer_authorization() -> None:
    """Authorization header is ``Bearer <api_password>``."""
    captured: dict = {}
    with _spy_async_client(captured):
        asyncio.run(HttpApiClient(_sensenova_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="sensenova-6.7-flash-lite",
        ))
    headers = captured["post_headers"]
    assert headers.get("Authorization") == "Bearer sensenova-test-key"
    assert headers.get("Content-Type") == "application/json"


def test_sensenova_request_payload_shape() -> None:
    """Payload contains model, messages, stream=False, and configured max_tokens."""
    captured: dict = {}
    with _spy_async_client(captured):
        asyncio.run(HttpApiClient(_sensenova_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="sensenova-6.7-flash-lite",
        ))
    payload = captured["post_payload"]
    assert payload["model"] == "sensenova-6.7-flash-lite"
    assert payload["messages"] == [{"role": "user", "content": "ping"}]
    assert payload["stream"] is False
    assert payload["max_tokens"] == 8_192


def test_sensenova_200_response_returns_content_and_usage() -> None:
    """Standard OpenAI-shape 200 response yields content and normalized usage."""
    captured: dict = {}
    body = {
        "id": "chatcmpl-abc",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 22,
            "total_tokens": 33,
            "prompt_tokens_details": {"cached_tokens": 4},
        },
    }
    with _spy_async_client(captured, body=body):
        content, usage = asyncio.run(
            HttpApiClient(_sensenova_settings()).call(
                [{"role": "user", "content": "ping"}],
                model="sensenova-6.7-flash-lite",
            )
        )
    assert content == "pong"
    assert usage == {
        "prompt_tokens": 11,
        "completion_tokens": 22,
        "total_tokens": 33,
        "cached_tokens": 4,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }


def test_sensenova_4xx_response_surfaces_message() -> None:
    """SenseNova ``{"error": {"message": ...}}`` bodies must raise ApiError."""
    # Re-resolve the ApiError class via the (possibly reloaded) api_client
    # module: a top-level import would bind a stale class identity, and
    # test_config.test_client_factory reloads api_client_module.
    ApiError_cls = api_client_module.ApiError

    captured: dict = {}
    body = {
        "error": {
            "type": "invalid_request_error",
            "code": "3",
            "message": "invalid temperature, should in [0,2].",
        }
    }
    with _spy_async_client(captured, status_code=400, body=body):
        try:
            asyncio.run(HttpApiClient(_sensenova_settings()).call(
                [{"role": "user", "content": "ping"}],
                model="sensenova-6.7-flash-lite",
            ))
        except ApiError_cls as exc:
            assert "invalid temperature" in str(exc), (
                f"expected 'invalid temperature' in {str(exc)!r}"
            )
        else:
            pytest.fail("expected HttpApiClient.call to raise ApiError on 4xx")


def test_sensenova_response_without_usage_returns_none() -> None:
    """Provider that omits ``usage`` must not crash; content still returned."""
    captured: dict = {}
    body = {
        "id": "chatcmpl-abc",
        "object": "chat.completion",
        "choices": [{"message": {"content": "pong"}}],
        # No "usage" key on purpose — _normalize_usage returns None.
    }
    with _spy_async_client(captured, body=body):
        content, usage = asyncio.run(HttpApiClient(_sensenova_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="sensenova-6.7-flash-lite",
        ))
    assert content == "pong"
    assert usage is None
