"""Contract tests for the deepseek provider.

These tests pin down the protocol-level contract between HttpApiClient and the
DeepSeek official API endpoint — they do **not** perform real network calls.
They mirror test_sensenova_contracts.py because deepseek is a plain
OpenAI-compatible Bearer endpoint fully covered by the existing generic HTTP
client, so the wire shape is locked here from the published docs
(https://api-docs.deepseek.com/).

What we lock down here:

1. Settings layer: PROVIDER=deepseek resolves to the documented endpoint /
   model / credential fallback chain.
2. HTTP layer: HttpApiClient.call posts to the documented URL, sends
   ``Authorization: Bearer <key>``, includes the expected payload fields, and
   returns the assistant content from the standard OpenAI shape.
3. Reasoning path: deepseek-v4-pro runs in thinking mode and returns a
   ``reasoning_content`` field alongside ``content``; the client must return
   ``content`` (the final answer) and ignore ``reasoning_content``.
4. Error path: DeepSeek's ``{"error": {"message": ...}}`` body on a non-200
   response is surfaced as ApiError with the upstream message, not swallowed.
5. Usage path: a 200 response's ``usage`` block (with the OpenAI-style
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
        "DEEPSEEK_API_KEY", "DEEPSEEK_API_URL", "DEEPSEEK_MODEL",
        "MCP_MAX_CONTEXT_CHARS", "MCP_MAX_TOKENS",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_deepseek_provider_profile_loaded() -> None:
    """The DEEPSEEK profile is registered and matches the documented contract."""
    from coding_bridge_mcp import providers

    assert "deepseek" in providers.PROVIDERS
    profile = providers.get_provider("deepseek")
    assert profile.mode == "http"
    assert profile.default_api_url == "https://api.deepseek.com/chat/completions"
    assert profile.default_model == "deepseek-v4-pro"
    assert profile.api_key_env_vars == ["API_KEY", "DEEPSEEK_API_KEY"]
    assert profile.api_url_env_vars == ["DEEPSEEK_API_URL"]
    assert profile.model_env_vars == ["DEEPSEEK_MODEL"]


def test_deepseek_settings_resolve() -> None:
    os.environ["PROVIDER"] = "deepseek"
    os.environ["API_KEY"] = "deepseek-test-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "deepseek"
    assert settings.api_url == "https://api.deepseek.com/chat/completions"
    assert settings.default_model == "deepseek-v4-pro"
    assert settings.api_password == "deepseek-test-key"


def test_deepseek_url_and_model_override_takes_effect() -> None:
    os.environ["PROVIDER"] = "deepseek"
    os.environ["DEEPSEEK_API_KEY"] = "k"
    os.environ["DEEPSEEK_API_URL"] = "https://deepseek-staging.example.com/v1/chat/completions"
    os.environ["DEEPSEEK_MODEL"] = "deepseek-v4-flash"
    reload(config_module)
    settings = config_module.load_settings()

    assert settings.api_url == "https://deepseek-staging.example.com/v1/chat/completions"
    assert settings.default_model == "deepseek-v4-flash"


def test_deepseek_missing_key_raises() -> None:
    os.environ["PROVIDER"] = "deepseek"
    reload(config_module)
    settings = config_module.load_settings()
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        config_module.validate_settings(settings)


# ---------------------------------------------------------------------------
# HTTP layer — wire-shape contract with mocked httpx
# ---------------------------------------------------------------------------


def _deepseek_settings() -> Settings:
    return Settings(
        provider="deepseek",
        mode="http",
        api_url="https://api.deepseek.com/chat/completions",
        api_password="deepseek-test-key",
        default_model="deepseek-v4-pro",
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


def test_deepseek_posts_to_documented_endpoint() -> None:
    """POST URL is exactly the DeepSeek official chat endpoint."""
    captured: dict = {}
    with _spy_async_client(captured):
        asyncio.run(HttpApiClient(_deepseek_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="deepseek-v4-pro",
        ))
    assert captured["post_url"] == "https://api.deepseek.com/chat/completions"


def test_deepseek_sends_bearer_authorization() -> None:
    """Authorization header is ``Bearer <api_password>``."""
    captured: dict = {}
    with _spy_async_client(captured):
        asyncio.run(HttpApiClient(_deepseek_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="deepseek-v4-pro",
        ))
    headers = captured["post_headers"]
    assert headers.get("Authorization") == "Bearer deepseek-test-key"
    assert headers.get("Content-Type") == "application/json"


def test_deepseek_request_payload_shape() -> None:
    """Payload contains model, messages, stream=False, and configured max_tokens."""
    captured: dict = {}
    with _spy_async_client(captured):
        asyncio.run(HttpApiClient(_deepseek_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="deepseek-v4-pro",
        ))
    payload = captured["post_payload"]
    assert payload["model"] == "deepseek-v4-pro"
    assert payload["messages"] == [{"role": "user", "content": "ping"}]
    assert payload["stream"] is False
    assert payload["max_tokens"] == 8_192


def test_deepseek_200_response_returns_content_and_usage() -> None:
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
            HttpApiClient(_deepseek_settings()).call(
                [{"role": "user", "content": "ping"}],
                model="deepseek-v4-pro",
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


def test_deepseek_thinking_response_returns_final_content_not_reasoning() -> None:
    """deepseek-v4-pro thinking mode adds ``reasoning_content``; we return only
    the final ``content`` and ignore the chain-of-thought field."""
    captured: dict = {}
    body = {
        "id": "chatcmpl-xyz",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "reasoning_content": "let me think step by step...",
                "content": "final answer",
            },
            "finish_reason": "stop",
        }],
    }
    with _spy_async_client(captured, body=body):
        content, usage = asyncio.run(HttpApiClient(_deepseek_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="deepseek-v4-pro",
        ))
    assert content == "final answer"


def test_deepseek_empty_content_raises_with_reasoning_hint() -> None:
    """Thinking mode may return empty ``content`` with only ``reasoning_content``.

    The client must NOT silently return an empty string (a review tool would
    then proceed on empty input). It must raise ``ApiError`` with a hint that
    points at the reasoning-only response, so the caller can retry or raise
    max_tokens.
    """
    ApiError_cls = api_client_module.ApiError
    captured: dict = {}
    body = {
        "id": "chatcmpl-empty",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "reasoning_content": "thoughts but no conclusion",
                "content": "",
            },
            "finish_reason": "stop",
        }],
    }
    with _spy_async_client(captured, body=body):
        with pytest.raises(ApiError_cls, match="empty content"):
            asyncio.run(HttpApiClient(_deepseek_settings()).call(
                [{"role": "user", "content": "ping"}],
                model="deepseek-v4-pro",
            ))


def test_deepseek_missing_content_field_raises_structure_error() -> None:
    """A ``message`` with no ``content`` key at all hits the structural guard.

    This is distinct from ``content: ""``: a missing key raises ``KeyError``,
    caught by the first ``except`` and surfaced as an "Unexpected API response
    structure" ``ApiError`` — never reaching the ``if not content`` branch, so
    no reasoning hint is appended. Pinned here so a future refactor that
    collapses the two paths must consciously update the contract.
    """
    ApiError_cls = api_client_module.ApiError
    captured: dict = {}
    body = {
        "id": "chatcmpl-no-content",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "reasoning_content": "thoughts only"},
            "finish_reason": "stop",
        }],
    }
    with _spy_async_client(captured, body=body):
        with pytest.raises(ApiError_cls, match="Unexpected API response structure"):
            asyncio.run(HttpApiClient(_deepseek_settings()).call(
                [{"role": "user", "content": "ping"}],
                model="deepseek-v4-pro",
            ))


def test_deepseek_4xx_response_surfaces_message() -> None:
    """DeepSeek ``{"error": {"message": ...}}`` bodies must raise ApiError."""
    # Re-resolve the ApiError class via the (possibly reloaded) api_client
    # module: a top-level import would bind a stale class identity, and
    # test_config.test_client_factory reloads api_client_module.
    ApiError_cls = api_client_module.ApiError

    captured: dict = {}
    body = {
        "error": {
            "message": "Authentication Fails, Your api key is invalid",
            "type": "authentication_error",
            "code": "invalid_request_error",
        }
    }
    with _spy_async_client(captured, status_code=401, body=body):
        try:
            asyncio.run(HttpApiClient(_deepseek_settings()).call(
                [{"role": "user", "content": "ping"}],
                model="deepseek-v4-pro",
            ))
        except ApiError_cls as exc:
            assert "api key is invalid" in str(exc), (
                f"expected 'api key is invalid' in {str(exc)!r}"
            )
        else:
            pytest.fail("expected HttpApiClient.call to raise ApiError on 4xx")


def test_deepseek_response_without_usage_returns_none() -> None:
    """Provider that omits ``usage`` must not crash; content still returned."""
    captured: dict = {}
    body = {
        "id": "chatcmpl-abc",
        "object": "chat.completion",
        "choices": [{"message": {"content": "pong"}}],
        # No "usage" key on purpose — _normalize_usage returns None.
    }
    with _spy_async_client(captured, body=body):
        content, usage = asyncio.run(HttpApiClient(_deepseek_settings()).call(
            [{"role": "user", "content": "ping"}],
            model="deepseek-v4-pro",
        ))
    assert content == "pong"
    assert usage is None
