"""Provider profiles for OpenAI-compatible coding plan services."""

import os
import warnings
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ProviderProfile:
    """Describes a single provider/backend configuration."""

    name: str
    mode: str  # 当前仅支持 "http"（保留字段以备未来协议扩展）
    default_api_url: str
    default_model: str
    default_max_context_chars: int
    default_max_tokens: int
    api_key_env_vars: List[str]
    api_url_env_vars: List[str]
    model_env_vars: List[str]


# iFlytek / Xfyun Coding Plan profile
XFYUN_CODING = ProviderProfile(
    name="xfyun-coding",
    mode="http",
    default_api_url="https://maas-coding-api.cn-huabei-1.xf-yun.com/v2/chat/completions",
    default_model="astron-code-latest",
    default_max_context_chars=1_048_576,
    default_max_tokens=8_192,
    api_key_env_vars=["SPARK_API_KEY", "API_KEY"],
    api_url_env_vars=["SPARK_API_URL"],
    model_env_vars=["SPARK_DEFAULT_MODEL"],
)

# Volcano Engine / Ark profiles
VOLCENGINE_CODING = ProviderProfile(
    name="volcengine-coding",
    mode="http",
    default_api_url="https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions",
    default_model="ark-code-latest",
    default_max_context_chars=1_048_576,
    default_max_tokens=8_192,
    api_key_env_vars=["VOLCENGINE_API_KEY", "API_KEY"],
    api_url_env_vars=["VOLCENGINE_API_URL", "ARK_API_URL"],
    model_env_vars=["VOLCENGINE_MODEL", "ARK_MODEL"],
)

# Baidu Qianfan Token Plan profile (OpenAI-compatible).
# Endpoint: /v2/tokenplan/personal/chat/completions.
QIANFAN_CODING = ProviderProfile(
    name="qianfan-coding",
    mode="http",
    default_api_url="https://qianfan.baidubce.com/v2/tokenplan/personal/chat/completions",
    default_model="glm-5.2",
    default_max_context_chars=1_048_576,
    default_max_tokens=8_192,
    api_key_env_vars=["QIANFAN_API_KEY", "API_KEY"],
    api_url_env_vars=["QIANFAN_API_URL"],
    model_env_vars=["QIANFAN_MODEL"],
)

# OpenCode Go profile (OpenAI-compatible subset: GLM / Kimi / DeepSeek / MiMo).
# MiniMax / Qwen models speak the Anthropic protocol (/v1/messages) and are NOT
# covered by HttpApiClient — they would need a separate Anthropic client.
OPENCODE_GO = ProviderProfile(
    name="opencode-go",
    mode="http",
    default_api_url="https://opencode.ai/zen/go/v1/chat/completions",
    default_model="glm-5.2",
    default_max_context_chars=1_048_576,
    default_max_tokens=8_192,
    api_key_env_vars=["OPENCODE_API_KEY", "API_KEY"],
    api_url_env_vars=["OPENCODE_API_URL"],
    model_env_vars=["OPENCODE_MODEL"],
)

# SenseNova (商汤日日新) Token Plan profile (OpenAI-compatible).
# Auth is a plain ``Authorization: Bearer sk-...`` key (no JWT signing), so the
# generic HttpApiClient covers it. The chat endpoint is /v1/chat/completions;
# the ``sensenova-u1-fast`` model is image-generation-only (/v1/images/generations)
# and is NOT a valid chat model, so it is intentionally not the default here.
# ``deepseek-v4-flash`` (1M context, reasoning) is the default — its review
# quality is markedly better than ``sensenova-6.7-flash-lite``. The trade-off:
# the Token Plan quota is very low (tpm wall hit easily), so prefer the
# flash-lite model via SENSENOVA_MODEL when throughput matters more than depth.
SENSENOVA = ProviderProfile(
    name="sensenova",
    mode="http",
    default_api_url="https://token.sensenova.cn/v1/chat/completions",
    default_model="deepseek-v4-flash",
    default_max_context_chars=1_048_576,
    default_max_tokens=8_192,
    api_key_env_vars=["SENSENOVA_API_KEY", "API_KEY"],
    api_url_env_vars=["SENSENOVA_API_URL"],
    model_env_vars=["SENSENOVA_MODEL"],
)

# DeepSeek official API profile (OpenAI-compatible).
# Auth is a plain ``Authorization: Bearer sk-...`` key, so the generic
# HttpApiClient covers it with no protocol-layer code. Base URL is
# https://api.deepseek.com; the chat endpoint is /chat/completions (no /v1
# needed — https://api.deepseek.com/v1 also works as base). Chat models:
# ``deepseek-v4-pro`` (default here) and ``deepseek-v4-flash``; the legacy
# ``deepseek-chat`` / ``deepseek-reasoner`` names are deprecated on 2026-07-24
# (they map to the non-thinking / thinking modes of deepseek-v4-flash).
# The "pro" model runs in thinking mode, so responses carry a
# ``reasoning_content`` field alongside ``content``; HttpApiClient only reads
# ``content`` (the final answer), which is the desired behavior for review.
DEEPSEEK = ProviderProfile(
    name="deepseek",
    mode="http",
    default_api_url="https://api.deepseek.com/chat/completions",
    default_model="deepseek-v4-pro",
    default_max_context_chars=1_048_576,
    default_max_tokens=8_192,
    api_key_env_vars=["DEEPSEEK_API_KEY", "API_KEY"],
    api_url_env_vars=["DEEPSEEK_API_URL"],
    model_env_vars=["DEEPSEEK_MODEL"],
)

PROVIDERS = {
    XFYUN_CODING.name: XFYUN_CODING,
    VOLCENGINE_CODING.name: VOLCENGINE_CODING,
    QIANFAN_CODING.name: QIANFAN_CODING,
    OPENCODE_GO.name: OPENCODE_GO,
    SENSENOVA.name: SENSENOVA,
    DEEPSEEK.name: DEEPSEEK,
}

# Default provider used when neither PROVIDER nor a valid SPARK_MODE is set.
DEFAULT_PROVIDER_NAME = XFYUN_CODING.name

# Backward-compatible mapping from legacy SPARK_MODE to provider names.
# SPARK_MODE is deprecated; prefer the PROVIDER environment variable.
# The removed "http" / "websocket" modes no longer exist and will raise an
# explicit error instead of silently falling back to the default provider.
SPARK_MODE_MAP = {
    "coding": XFYUN_CODING.name,
}


def resolve_provider_name() -> str:
    """Determine active provider from PROVIDER or legacy SPARK_MODE env vars."""
    provider = os.environ.get("PROVIDER", "").strip().lower()
    if provider:
        if provider not in PROVIDERS:
            raise ValueError(
                f"Invalid PROVIDER '{provider}'. Supported: {', '.join(PROVIDERS)}"
            )
        return provider

    spark_mode = os.environ.get("SPARK_MODE", "").strip().lower()
    if spark_mode:
        if spark_mode in ("http", "websocket"):
            raise ValueError(
                f"SPARK_MODE='{spark_mode}' is no longer supported. "
                f"Use PROVIDER='{DEFAULT_PROVIDER_NAME}' instead."
            )
        if spark_mode not in SPARK_MODE_MAP:
            raise ValueError(
                f"Unsupported SPARK_MODE '{spark_mode}'. "
                f"Use PROVIDER='{DEFAULT_PROVIDER_NAME}' instead."
            )
        warnings.warn(
            f"SPARK_MODE='{spark_mode}' is deprecated. "
            f"Use PROVIDER='{DEFAULT_PROVIDER_NAME}' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return SPARK_MODE_MAP[spark_mode]

    return DEFAULT_PROVIDER_NAME


def get_provider(name: str) -> ProviderProfile:
    if not name:
        raise ValueError("Provider name must not be empty")
    if name not in PROVIDERS:
        raise ValueError(
            f"Unknown provider '{name}'. Supported: {', '.join(PROVIDERS)}"
        )
    return PROVIDERS[name]
