"""Tests for configuration loading."""

import os
from importlib import reload

import pytest

from coding_bridge_mcp import config as config_module
from coding_bridge_mcp import api_client as api_client_module


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Clear provider-related env vars before each test."""
    for key in [
        "PROVIDER",
        "SPARK_MODE",
        "API_KEY",
        "SPARK_API_PASSWORD",
        "SPARK_API_KEY",
        "SPARK_API_URL",
        "SPARK_DEFAULT_MODEL",
        "SPARK_MAX_CONTEXT_CHARS",
        "SPARK_MAX_TOKENS",
        "VOLCENGINE_API_KEY",
        "VOLCENGINE_API_URL",
        "VOLCENGINE_MODEL",
        "QIANFAN_API_KEY",
        "QIANFAN_API_URL",
        "QIANFAN_MODEL",
        "OPENCODE_API_KEY",
        "OPENCODE_API_URL",
        "OPENCODE_MODEL",
        "SENSENOVA_API_KEY",
        "SENSENOVA_API_URL",
        "SENSENOVA_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_URL",
        "DEEPSEEK_MODEL",
        "MCP_MAX_CONTEXT_CHARS",
        "MCP_MAX_TOKENS",
    ]:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("provider", ["xfyun-http", "xfyun-websocket", "invalid"])
def test_invalid_provider_raises(provider, monkeypatch):
    monkeypatch.setenv("PROVIDER", provider)
    reload(config_module)
    with pytest.raises(ValueError, match="Invalid PROVIDER"):
        config_module.load_settings()


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


def test_qianfan_defaults():
    os.environ["PROVIDER"] = "qianfan-coding"
    os.environ["QIANFAN_API_KEY"] = "qianfan-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "qianfan-coding"
    assert settings.mode == "http"
    assert settings.api_url == "https://qianfan.baidubce.com/v2/coding/chat/completions"
    assert settings.default_model == "qianfan-code-latest"
    assert settings.max_context_chars == 96000
    assert settings.max_tokens == 8192
    assert settings.api_password == "qianfan-key"


def test_qianfan_uses_generic_api_key():
    os.environ["PROVIDER"] = "qianfan-coding"
    os.environ["API_KEY"] = "generic-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"


def test_qianfan_api_key_takes_precedence_over_specific():
    # Lock first-match-wins semantics: API_KEY wins when both are set.
    os.environ["PROVIDER"] = "qianfan-coding"
    os.environ["API_KEY"] = "generic-key"
    os.environ["QIANFAN_API_KEY"] = "qianfan-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"


def test_opencode_defaults():
    os.environ["PROVIDER"] = "opencode-go"
    os.environ["OPENCODE_API_KEY"] = "oc-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "opencode-go"
    assert settings.mode == "http"
    assert settings.api_url == "https://opencode.ai/zen/go/v1/chat/completions"
    assert settings.default_model == "glm-5.2"
    assert settings.max_context_chars == 96000
    assert settings.max_tokens == 8192
    assert settings.api_password == "oc-key"


def test_opencode_uses_generic_api_key():
    os.environ["PROVIDER"] = "opencode-go"
    os.environ["API_KEY"] = "generic-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"


def test_opencode_api_key_takes_precedence_over_specific():
    # Lock first-match-wins semantics: API_KEY wins when both are set.
    os.environ["PROVIDER"] = "opencode-go"
    os.environ["API_KEY"] = "generic-key"
    os.environ["OPENCODE_API_KEY"] = "oc-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"


def test_sensenova_defaults():
    os.environ["PROVIDER"] = "sensenova"
    os.environ["SENSENOVA_API_KEY"] = "sn-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "sensenova"
    assert settings.mode == "http"
    assert settings.api_url == "https://token.sensenova.cn/v1/chat/completions"
    assert settings.default_model == "deepseek-v4-flash"
    assert settings.max_context_chars == 96000
    assert settings.max_tokens == 8192
    assert settings.api_password == "sn-key"


def test_sensenova_uses_generic_api_key():
    os.environ["PROVIDER"] = "sensenova"
    os.environ["API_KEY"] = "generic-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"


def test_sensenova_api_key_takes_precedence_over_specific():
    # Lock first-match-wins semantics: API_KEY wins when both are set.
    os.environ["PROVIDER"] = "sensenova"
    os.environ["API_KEY"] = "generic-key"
    os.environ["SENSENOVA_API_KEY"] = "sn-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"


def test_sensenova_model_override():
    os.environ["PROVIDER"] = "sensenova"
    os.environ["SENSENOVA_API_KEY"] = "sn-key"
    os.environ["SENSENOVA_MODEL"] = "sensenova-6.7-flash-lite"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.default_model == "sensenova-6.7-flash-lite"


def test_deepseek_defaults():
    os.environ["PROVIDER"] = "deepseek"
    os.environ["DEEPSEEK_API_KEY"] = "ds-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "deepseek"
    assert settings.mode == "http"
    assert settings.api_url == "https://api.deepseek.com/chat/completions"
    assert settings.default_model == "deepseek-v4-pro"
    assert settings.max_context_chars == 96000
    assert settings.max_tokens == 8192
    assert settings.api_password == "ds-key"


def test_deepseek_uses_generic_api_key():
    os.environ["PROVIDER"] = "deepseek"
    os.environ["API_KEY"] = "generic-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"


def test_deepseek_api_key_takes_precedence_over_specific():
    # Lock first-match-wins semantics: API_KEY wins when both are set.
    os.environ["PROVIDER"] = "deepseek"
    os.environ["API_KEY"] = "generic-key"
    os.environ["DEEPSEEK_API_KEY"] = "ds-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"


def test_deepseek_model_override():
    os.environ["PROVIDER"] = "deepseek"
    os.environ["DEEPSEEK_API_KEY"] = "ds-key"
    os.environ["DEEPSEEK_MODEL"] = "deepseek-v4-flash"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.default_model == "deepseek-v4-flash"


def test_coding_uses_generic_api_key():
    os.environ["PROVIDER"] = "xfyun-coding"
    os.environ["API_KEY"] = "generic-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"


def test_volcengine_uses_generic_api_key():
    os.environ["PROVIDER"] = "volcengine-coding"
    os.environ["API_KEY"] = "generic-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"


def test_coding_missing_key():
    os.environ["SPARK_MODE"] = "coding"
    reload(config_module)
    settings = config_module.load_settings()
    with pytest.raises(RuntimeError, match="SPARK_API_PASSWORD"):
        config_module.validate_settings(settings)


def test_deprecated_spark_mode_http_raises():
    os.environ["SPARK_MODE"] = "http"
    reload(config_module)
    with pytest.raises(ValueError, match="SPARK_MODE='http' is no longer supported"):
        config_module.load_settings()


def test_deprecated_spark_mode_websocket_raises():
    os.environ["SPARK_MODE"] = "websocket"
    reload(config_module)
    with pytest.raises(ValueError, match="SPARK_MODE='websocket' is no longer supported"):
        config_module.load_settings()


def test_client_factory():
    os.environ["SPARK_MODE"] = "coding"
    os.environ["SPARK_API_PASSWORD"] = "key"
    reload(config_module)
    reload(api_client_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)
    client = api_client_module.create_client(settings)
    assert isinstance(client, api_client_module.HttpApiClient)
