"""Tests for the PROXY configuration surface.

Covers four contract points:
1. Default is ``"false"`` (ignore environment, direct connect).
2. ``PROXY=true|env`` enables httpx ``trust_env=True``.
3. ``PROXY=custom`` requires both HTTP/HTTPS host+port; constructs an explicit
   ``proxy={scheme: httpx.Proxy(url)}`` mapping; ``trust_env=False``.
4. Invalid PROXY values, partial config, and out-of-range ports raise
   ``ValueError`` at load time (startup fail-fast).
"""

from __future__ import annotations

import asyncio
import os
from importlib import reload
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from coding_bridge_mcp import config as config_module
from coding_bridge_mcp.api_client import _build_client_kwargs, HttpApiClient


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "PROVIDER", "SPARK_MODE",
        "API_KEY", "SPARK_API_PASSWORD",
        "PROXY",
        "HTTP_PROXY_HOST", "HTTP_PROXY_PORT",
        "HTTP_PROXY_USER", "HTTP_PROXY_PASSWORD",
        "HTTPS_PROXY_HOST", "HTTPS_PROXY_PORT",
        "HTTPS_PROXY_USER", "HTTPS_PROXY_PASSWORD",
    ]:
        monkeypatch.delenv(key, raising=False)


def _make_settings(**overrides):
    """Build a Settings with the new proxy fields defaulted to ``(false, None, None)``."""
    from coding_bridge_mcp.config import Settings
    defaults = dict(
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
    defaults.update(overrides)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# Settings-level: PROXY env var parsing
# ---------------------------------------------------------------------------

def test_proxy_mode_defaults_to_false() -> None:
    """No PROXY env var ⇒ mode == 'false', no endpoints."""
    reload(config_module)
    settings = config_module.load_settings()
    assert settings.proxy_mode == "false"
    assert settings.proxy_http is None
    assert settings.proxy_https is None


def test_proxy_mode_true_aliases_env() -> None:
    os.environ["PROXY"] = "true"
    reload(config_module)
    settings = config_module.load_settings()
    assert settings.proxy_mode == "env"


def test_proxy_mode_accepts_env_keyword() -> None:
    os.environ["PROXY"] = "env"
    reload(config_module)
    settings = config_module.load_settings()
    assert settings.proxy_mode == "env"


def test_proxy_mode_invalid_raises() -> None:
    os.environ["PROXY"] = "bogus"
    reload(config_module)
    with pytest.raises(ValueError, match="Invalid PROXY value"):
        config_module.load_settings()


def test_proxy_custom_requires_both_schemes() -> None:
    """PROXY=custom with only HTTP configured ⇒ ValueError."""
    os.environ["PROXY"] = "custom"
    os.environ["HTTP_PROXY_HOST"] = "h.local"
    os.environ["HTTP_PROXY_PORT"] = "8080"
    reload(config_module)
    with pytest.raises(ValueError, match="BOTH HTTP and HTTPS proxies"):
        config_module.load_settings()


def test_proxy_custom_with_no_endpoints_raises() -> None:
    os.environ["PROXY"] = "custom"
    reload(config_module)
    with pytest.raises(ValueError, match="requires HTTP_PROXY_HOST/PORT"):
        config_module.load_settings()


def test_proxy_custom_parses_endpoints_with_auth() -> None:
    os.environ["PROXY"] = "custom"
    os.environ["HTTP_PROXY_HOST"] = "h.local"
    os.environ["HTTP_PROXY_PORT"] = "8080"
    os.environ["HTTP_PROXY_USER"] = "alice"
    os.environ["HTTP_PROXY_PASSWORD"] = "s3cret"
    os.environ["HTTPS_PROXY_HOST"] = "h.local"
    os.environ["HTTPS_PROXY_PORT"] = "8443"
    reload(config_module)
    settings = config_module.load_settings()
    assert settings.proxy_mode == "custom"
    assert settings.proxy_http is not None
    assert settings.proxy_http.host == "h.local"
    assert settings.proxy_http.port == 8080
    assert settings.proxy_http.username == "alice"
    assert settings.proxy_http.password == "s3cret"
    # URL form requires percent-encoding for user/pass.
    assert "alice:s3cret" in settings.proxy_http.url()


def test_proxy_custom_rejects_password_without_user() -> None:
    os.environ["PROXY"] = "custom"
    os.environ["HTTP_PROXY_HOST"] = "h.local"
    os.environ["HTTP_PROXY_PORT"] = "8080"
    os.environ["HTTPS_PROXY_HOST"] = "h.local"
    os.environ["HTTPS_PROXY_PORT"] = "8443"
    os.environ["HTTP_PROXY_PASSWORD"] = "orphan"
    reload(config_module)
    with pytest.raises(ValueError, match="PASSWORD given without"):
        config_module.load_settings()


def test_proxy_custom_rejects_out_of_range_port() -> None:
    os.environ["PROXY"] = "custom"
    os.environ["HTTP_PROXY_HOST"] = "h.local"
    os.environ["HTTP_PROXY_PORT"] = "99999"
    os.environ["HTTPS_PROXY_HOST"] = "h.local"
    os.environ["HTTPS_PROXY_PORT"] = "8443"
    reload(config_module)
    with pytest.raises(ValueError, match="out of range"):
        config_module.load_settings()


# ---------------------------------------------------------------------------
# _build_client_kwargs: contract for httpx.AsyncClient construction
# ---------------------------------------------------------------------------

def test_kwargs_false_mode_disables_trust_env() -> None:
    s = _make_settings(proxy_mode="false")
    kw = _build_client_kwargs(s)
    assert kw == {"timeout": 30.0, "trust_env": False}


def test_kwargs_env_mode_enables_trust_env() -> None:
    s = _make_settings(proxy_mode="env")
    kw = _build_client_kwargs(s)
    assert kw == {"timeout": 30.0, "trust_env": True}


def test_kwargs_custom_mode_uses_explicit_proxy_dict() -> None:
    s = _make_settings(
        proxy_mode="custom",
        proxy_http=config_module.ProxyEndpoint("http", "h.local", 8080),
        proxy_https=config_module.ProxyEndpoint("https", "h.local", 8443),
    )
    kw = _build_client_kwargs(s)
    assert kw["trust_env"] is False
    assert isinstance(kw["proxy"], dict)
    assert "http://" in kw["proxy"]
    assert "https://" in kw["proxy"]
    assert isinstance(kw["proxy"]["http://"], httpx.Proxy)
    assert "h.local:8080" in str(kw["proxy"]["http://"].url)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Integration: HttpApiClient.call constructs httpx.AsyncClient per mode
# ---------------------------------------------------------------------------

def _spy_async_client(captured: dict, response_payload: dict | None = None) -> MagicMock:
    payload = response_payload or {
        "code": 0,
        "choices": [{"message": {"content": "ok"}}],
    }

    def _spy(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = dict(kwargs)
        fake = MagicMock()
        fake.__aenter__ = AsyncMock(return_value=fake)
        fake.__aexit__ = AsyncMock(return_value=None)
        post_response = MagicMock()
        post_response.status_code = 200
        post_response.json.return_value = payload
        fake.post = AsyncMock(return_value=post_response)
        return fake

    return patch("httpx.AsyncClient", side_effect=_spy)


def test_http_client_false_mode_in_hostile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """False mode must ignore HTTP_PROXY even when set."""
    monkeypatch.setenv("HTTP_PROXY", "http://attacker.invalid:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://attacker.invalid:3128")
    captured: dict = {}
    s = _make_settings(proxy_mode="false")
    with _spy_async_client(captured):
        asyncio.run(HttpApiClient(s).call(
            [{"role": "user", "content": "hi"}], model="astron-code-latest"
        ))
    assert captured["kwargs"]["trust_env"] is False
    assert "proxy" not in captured["kwargs"]


def test_http_client_env_mode_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    s = _make_settings(proxy_mode="env")
    with _spy_async_client(captured):
        asyncio.run(HttpApiClient(s).call(
            [{"role": "user", "content": "hi"}], model="astron-code-latest"
        ))
    assert captured["kwargs"]["trust_env"] is True
    assert "proxy" not in captured["kwargs"]


def test_http_client_custom_mode_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    s = _make_settings(
        proxy_mode="custom",
        proxy_http=config_module.ProxyEndpoint("http", "h.local", 8080),
        proxy_https=config_module.ProxyEndpoint("https", "h.local", 8443),
    )
    with _spy_async_client(captured):
        asyncio.run(HttpApiClient(s).call(
            [{"role": "user", "content": "hi"}], model="astron-code-latest"
        ))
    assert captured["kwargs"]["trust_env"] is False
    proxy = captured["kwargs"]["proxy"]
    assert isinstance(proxy, dict)
    assert "http://" in proxy and "https://" in proxy
    assert "h.local:8080" in str(proxy["http://"].url)  # type: ignore[attr-defined]
    assert "h.local:8443" in str(proxy["https://"].url)  # type: ignore[attr-defined]
