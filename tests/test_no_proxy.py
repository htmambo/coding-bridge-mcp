"""Regression: HttpApiClient must never honor proxy environment variables.

httpx.AsyncClient reads HTTP_PROXY/HTTPS_PROXY/ALL_PROXY/NO_PROXY from the
environment by default (``trust_env=True``). The project policy is to always
connect directly to provider endpoints, regardless of how the operator's shell
is configured. See README §5 and docs/Task/TASK_NO_PROXY_PLAN.md.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coding_bridge_mcp.api_client import HttpApiClient
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


def test_http_client_disables_trust_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``httpx.AsyncClient`` must be constructed with ``trust_env=False``.

    This is the single line that defeats environment-variable proxy injection
    (HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / NO_PROXY). If a future refactor
    drops the kwarg, this test fails — which is the point.
    """
    # Force a hostile proxy env so a regression that re-enables trust_env
    # would actually try to use it.
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("ALL_PROXY", "socks5://proxy.invalid:1080")

    captured: dict[str, object] = {}

    def _spy(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        # Return an async context manager whose post() returns a fake 200.
        fake = MagicMock()
        fake.__aenter__ = AsyncMock(return_value=fake)
        fake.__aexit__ = AsyncMock(return_value=None)

        post_response = MagicMock()
        post_response.status_code = 200
        post_response.json.return_value = {
            "code": 0,
            "choices": [{"message": {"content": "ok"}}],
        }
        fake.post = AsyncMock(return_value=post_response)
        return fake

    with patch("httpx.AsyncClient", side_effect=_spy):
        import asyncio
        client = HttpApiClient(_settings())
        asyncio.run(client.call([{"role": "user", "content": "hi"}], model="astron-code-latest"))

    assert captured.get("trust_env") is False, (
        "HttpApiClient must construct httpx.AsyncClient with trust_env=False; "
        f"got kwargs={captured!r}"
    )


def test_http_client_does_not_pass_explicit_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Belt-and-suspenders: no ``proxy=`` kwarg either.

    Even if a future change re-enables ``trust_env=True``, an explicit
    ``proxy=None`` is the strongest signal that the call site intends a
    direct connection. Both layers together close the regression window.
    """
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")

    captured: dict[str, object] = {}

    def _spy(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        fake = MagicMock()
        fake.__aenter__ = AsyncMock(return_value=fake)
        fake.__aexit__ = AsyncMock(return_value=None)
        post_response = MagicMock()
        post_response.status_code = 200
        post_response.json.return_value = {
            "code": 0,
            "choices": [{"message": {"content": "ok"}}],
        }
        fake.post = AsyncMock(return_value=post_response)
        return fake

    with patch("httpx.AsyncClient", side_effect=_spy):
        import asyncio
        client = HttpApiClient(_settings())
        asyncio.run(client.call([{"role": "user", "content": "hi"}], model="astron-code-latest"))

    # trust_env=False is the documented knob; proxy=None is a redundant guard.
    assert captured.get("trust_env") is False
    # We do NOT require proxy=None to be present — the test contract is that
    # if it IS passed, it must be None (never a proxy URL). The current code
    # omits it entirely, which is also acceptable.
    if "proxy" in captured:
        assert captured["proxy"] is None, (
            f"HttpApiClient must never pass a proxy URL; got proxy={captured['proxy']!r}"
        )
