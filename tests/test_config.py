"""Tests for configuration loading."""

import os
from importlib import reload

import pytest

from coding_bridge_mcp import config as config_module
from coding_bridge_mcp import spark_client as spark_client_module


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Clear provider-related env vars before each test."""
    for key in [
        "PROVIDER",
        "SPARK_MODE",
        "SPARK_API_PASSWORD",
        "SPARK_API_KEY",
        "SPARK_APP_ID",
        "SPARK_API_SECRET",
        "SPARK_API_URL",
        "SPARK_WS_URL",
        "SPARK_DEFAULT_MODEL",
        "SPARK_MAX_CONTEXT_CHARS",
        "SPARK_MAX_TOKENS",
        "VOLCENGINE_API_KEY",
        "VOLCENGINE_API_URL",
        "VOLCENGINE_MODEL",
        "MCP_MAX_CONTEXT_CHARS",
        "MCP_MAX_TOKENS",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_coding_defaults():
    os.environ["SPARK_MODE"] = "coding"
    os.environ["SPARK_API_PASSWORD"] = "key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "xfyun-coding"
    assert settings.mode == "http"
    assert "maas-coding-api" in settings.api_url
    assert settings.default_model == "astron-code-latest"
    assert settings.max_context_chars == 96000
    assert settings.max_tokens == 8192


def test_provider_coding():
    os.environ["PROVIDER"] = "xfyun-coding"
    os.environ["SPARK_API_PASSWORD"] = "key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "xfyun-coding"
    assert settings.mode == "http"


def test_http_defaults():
    os.environ["SPARK_MODE"] = "http"
    os.environ["SPARK_API_PASSWORD"] = "pwd"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "xfyun-http"
    assert settings.mode == "http"
    assert "spark-api-open" in settings.api_url
    assert settings.default_model == "4.0Ultra"


def test_websocket_defaults():
    os.environ["SPARK_MODE"] = "websocket"
    os.environ["SPARK_APP_ID"] = "appid"
    os.environ["SPARK_API_KEY"] = "apikey"
    os.environ["SPARK_API_SECRET"] = "secret"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "xfyun-websocket"
    assert settings.mode == "websocket"
    assert settings.app_id == "appid"
    assert settings.api_key == "apikey"
    assert settings.api_secret == "secret"


def test_volcengine_defaults():
    os.environ["PROVIDER"] = "volcengine-coding"
    os.environ["VOLCENGINE_API_KEY"] = "volc-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "volcengine-coding"
    assert settings.mode == "http"
    assert "ark.cn-beijing.volces.com" in settings.api_url
    assert settings.default_model == "ark-code-latest"
    assert settings.api_password == "volc-key"


def test_coding_missing_key():
    os.environ["SPARK_MODE"] = "coding"
    reload(config_module)
    settings = config_module.load_settings()
    with pytest.raises(RuntimeError, match="SPARK_API_PASSWORD"):
        config_module.validate_settings(settings)


def test_client_factory():
    os.environ["SPARK_MODE"] = "coding"
    os.environ["SPARK_API_PASSWORD"] = "key"
    reload(config_module)
    reload(spark_client_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)
    client = spark_client_module.create_client(settings)
    assert isinstance(client, spark_client_module.HttpSparkClient)
