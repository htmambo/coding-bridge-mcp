"""Contract tests for the qianfan-coding provider.

These tests pin down the protocol-level contract between HttpApiClient and the
Baidu Qianfan Coding Plan endpoint — they do **not** perform real network
calls. They exist because the existing test_volcengine_live.py is opt-in (and
this task has no live key), and because the qianfan integration is the
first new provider added without first confirming the wire shape end-to-end.

What we lock down here:

1. Settings layer: PROVIDER=qianfan-coding resolves to the documented
   endpoint / model / credential fallback chain.
2. HTTP layer: HttpApiClient.call posts to the documented URL, sends
   ``Authorization: Bearer <key>``, includes the expected payload fields, and
   returns the assistant content from the standard OpenAI shape.
3. Error path: a non-200 response is surfaced as ApiError with a message
   drawn from the response body, not swallowed.
4. Usage path: a 200 response's ``usage`` block flows through _normalize_usage
   into the Anthropic-style schema our get_token_stats tool consumes.
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
        "QIANFAN_API_KEY", "QIANFAN_API_URL", "QIANFAN_MODEL",
        "MCP_MAX_CONTEXT_CHARS", "MCP_MAX_TOKENS",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_qianfan_provider_profile_loaded() -> None:
    """The QIANFAN_CODING profile is registered and matches the documented contract."""
    from coding_bridge_mcp import providers

    assert "qianfan-coding" in providers.PROVIDERS
    profile = providers.get_provider("qianfan-coding")
    assert profile.mode == "http"
    assert profile.default_api_url == "https://qianfan.baidubce.com/v2/coding"
    assert profile.default_model == "qianfan-code-latest"
    assert profile.api_key_env_vars == ["API_KEY", "QIANFAN_API_KEY"]
    assert profile.api_url_env_vars == ["QIANFAN_API_URL"]
    assert profile.model_env_vars == ["QIANFAN_MODEL"]


def test_qianfan_settings_resolve() -> None:
    os.environ["PROVIDER"] = "qianfan-coding"
    os.environ["API_KEY"] = "qianfan-test-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "qianfan-coding"
    assert settings.api_url == "https://qianfan.baidubce.com/v2/coding"
    assert settings.default_model == "qianfan-code-latest"
    assert settings.api_password == "qianfan-test-key"


def test_qianfan_url_override_takes_effect() -> None:
    os.environ["PROVIDER"] = "qianfan-coding"
    os.environ["QIANFAN_API_KEY"] = "k"
    os.environ["QIANFAN_API_URL"] = "https://qianfan-staging.example.com/v2/coding"
    os.environ["QIANFAN_MODEL"] = "qianfan-code-experimental"
    reload(config_module)
    settings = config_module.load_settings()

    assert settings.api_url == "https://qianfan-staging.example.com/v2/coding"
    assert settings.default_model == "qianfan-code-experimental"


def test_qianfan_missing_key_raises() -> None:
    os.environ["PROVIDER"] = "qianfan-coding"
    reload(config_module)
    settings = config_module.load_settings()
    with pytest.raises(RuntimeError, match="QIANFAN_API_KEY"):
        config_module.validate_settings(settings)


# ---------------------------------------------------------------------------
# HTTP layer — wire-shape contract with mocked httpx
# ---------------------------------------------------------------------------


def _qianfan_settings() -> Settings:
    return Settings(
        provider="qianfan-coding",
        mode="http",
        api_url="https://qianfan.baidubce.com/v2/coding",
        api_password="qianfan-test-key",
        app_id="",
        api_key="",
        api_secret="",
        default_model="qianfan-code-latest",
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
        "code": 0,
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
        # Some providers dump error bodies in non-JSON form; an api_client
        # fallback path uses ``response.text`` after ``response.json()`` fails.
        post_response.text = json.dumps(response_body, ensure_ascii=False)

        async def _post(*p_args, **p_kwargs):
            captured["post_url"] = p_args[0] if p_args else p_kwargs.get("url")
            captured["post_headers"] = p_kwargs.get("headers", {})
            captured["post_payload"] = p_kwargs.get("json")
            return post_response

        fake.post = _post
        return fake

    return patch("httpx.AsyncClient", side_effect=_spy)


def test_qianfan_posts_to_documented_endpoint() -> None:
    """POST URL is exactly the qianfan Coding Plan endpoint."""
    captured: dict = {}
    with _spy_async_client(captured):
        asyncio.run(HttpApiClient(_qianfan_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="qianfan-code-latest",
        ))
    assert captured["post_url"] == "https://qianfan.baidubce.com/v2/coding"


def test_qianfan_sends_bearer_authorization() -> None:
    """Authorization header is ``Bearer <api_password>``."""
    captured: dict = {}
    with _spy_async_client(captured):
        asyncio.run(HttpApiClient(_qianfan_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="qianfan-code-latest",
        ))
    headers = captured["post_headers"]
    assert headers.get("Authorization") == "Bearer qianfan-test-key"
    assert headers.get("Content-Type") == "application/json"


def test_qianfan_request_payload_shape() -> None:
    """Payload contains model, messages, stream=False, and configured max_tokens."""
    captured: dict = {}
    with _spy_async_client(captured):
        asyncio.run(HttpApiClient(_qianfan_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="qianfan-code-latest",
        ))
    payload = captured["post_payload"]
    assert payload["model"] == "qianfan-code-latest"
    assert payload["messages"] == [{"role": "user", "content": "ping"}]
    assert payload["stream"] is False
    assert payload["max_tokens"] == 8_192


def test_qianfan_200_response_returns_content_and_usage() -> None:
    """Standard OpenAI-shape 200 response yields content and normalized usage."""
    captured: dict = {}
    body = {
        "code": 0,
        "choices": [{"message": {"content": "pong"}}],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 22,
            "total_tokens": 33,
            "prompt_tokens_details": {"cached_tokens": 4},
        },
    }
    with _spy_async_client(captured, body=body):
        content, usage = asyncio.run(
            HttpApiClient(_qianfan_settings()).call(
                [{"role": "user", "content": "ping"}],
                model="qianfan-code-latest",
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


def test_qianfan_4xx_response_surfaces_message() -> None:
    """Non-200 responses must raise ApiError carrying the upstream message."""
    # Re-resolve the ApiError class via the (possibly reloaded) api_client
    # module: a top-level import would bind a stale class identity, and
    # test_config.test_client_factory reloads api_client_module.
    ApiError_cls = api_client_module.ApiError

    captured: dict = {}
    body = {"error": {"message": "invalid api key"}}
    with _spy_async_client(captured, status_code=401, body=body):
        try:
            asyncio.run(HttpApiClient(_qianfan_settings()).call(
                [{"role": "user", "content": "ping"}],
                model="qianfan-code-latest",
            ))
        except ApiError_cls as exc:
            assert "invalid api key" in str(exc), (
                f"expected 'invalid api key' in {str(exc)!r}"
            )
        else:
            pytest.fail("expected HttpApiClient.call to raise ApiError on 4xx")


def test_qianfan_response_without_usage_returns_none() -> None:
    """Provider that omits ``usage`` must not crash; content still returned."""
    captured: dict = {}
    body = {
        "code": 0,
        "choices": [{"message": {"content": "pong"}}],
        # No "usage" key on purpose — _normalize_usage returns None.
    }
    with _spy_async_client(captured, body=body):
        content, usage = asyncio.run(HttpApiClient(_qianfan_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="qianfan-code-latest",
        ))
    assert content == "pong"
    assert usage is None
