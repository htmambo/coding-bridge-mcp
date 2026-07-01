"""Provider profiles for OpenAI-compatible coding plan services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ProviderProfile:
    """Describes a single provider/backend configuration."""

    name: str
    mode: str  # "http" or "websocket"
    default_api_url: str
    default_model: str
    default_max_context_chars: int
    default_max_tokens: int
    api_key_env_vars: List[str]
    api_url_env_vars: List[str]
    model_env_vars: List[str]


# iFlytek / Xfyun profiles
XFYUN_CODING = ProviderProfile(
    name="xfyun-coding",
    mode="http",
    default_api_url="https://maas-coding-api.cn-huabei-1.xf-yun.com/v2/chat/completions",
    default_model="astron-code-latest",
    default_max_context_chars=96_000,
    default_max_tokens=8_192,
    api_key_env_vars=["API_KEY", "SPARK_API_PASSWORD", "SPARK_API_KEY"],
    api_url_env_vars=["SPARK_API_URL"],
    model_env_vars=["SPARK_DEFAULT_MODEL"],
)

XFYUN_HTTP = ProviderProfile(
    name="xfyun-http",
    mode="http",
    default_api_url="https://spark-api-open.xf-yun.com/v1/chat/completions",
    default_model="4.0Ultra",
    default_max_context_chars=24_000,
    default_max_tokens=4_096,
    api_key_env_vars=["API_KEY", "SPARK_API_PASSWORD", "SPARK_API_KEY"],
    api_url_env_vars=["SPARK_API_URL"],
    model_env_vars=["SPARK_DEFAULT_MODEL"],
)

XFYUN_WEBSOCKET = ProviderProfile(
    name="xfyun-websocket",
    mode="websocket",
    default_api_url="",
    default_model="4.0Ultra",
    default_max_context_chars=24_000,
    default_max_tokens=4_096,
    api_key_env_vars=[],  # WS uses SPARK_API_KEY separately for signing
    api_url_env_vars=["SPARK_WS_URL"],
    model_env_vars=["SPARK_DEFAULT_MODEL"],
)

# Volcano Engine / Ark profiles
VOLCENGINE_CODING = ProviderProfile(
    name="volcengine-coding",
    mode="http",
    default_api_url="https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions",
    default_model="ark-code-latest",
    default_max_context_chars=128_000,
    default_max_tokens=8_192,
    api_key_env_vars=["API_KEY", "VOLCENGINE_API_KEY", "ARK_API_KEY"],
    api_url_env_vars=["VOLCENGINE_API_URL", "ARK_API_URL"],
    model_env_vars=["VOLCENGINE_MODEL", "ARK_MODEL", "SPARK_DEFAULT_MODEL"],
)

# Baidu Qianfan Coding Plan profile (OpenAI-compatible).
QIANFAN_CODING = ProviderProfile(
    name="qianfan-coding",
    mode="http",
    # Path suffix /chat/completions is appended by the platform itself
    # (千帆 Coding Plan 在基础 URL /v2/coding 之后自动追加 OpenAI 标准路径);
    # the complete endpoint is therefore /v2/coding/chat/completions.
    default_api_url="https://qianfan.baidubce.com/v2/coding/chat/completions",
    default_model="qianfan-code-latest",
    default_max_context_chars=96_000,
    default_max_tokens=8_192,
    api_key_env_vars=["API_KEY", "QIANFAN_API_KEY"],
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
    default_max_context_chars=96_000,
    default_max_tokens=8_192,
    api_key_env_vars=["API_KEY", "OPENCODE_API_KEY"],
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
    default_max_context_chars=96_000,
    default_max_tokens=8_192,
    api_key_env_vars=["API_KEY", "SENSENOVA_API_KEY"],
    api_url_env_vars=["SENSENOVA_API_URL"],
    model_env_vars=["SENSENOVA_MODEL"],
)

PROVIDERS = {
    XFYUN_CODING.name: XFYUN_CODING,
    XFYUN_HTTP.name: XFYUN_HTTP,
    XFYUN_WEBSOCKET.name: XFYUN_WEBSOCKET,
    VOLCENGINE_CODING.name: VOLCENGINE_CODING,
    QIANFAN_CODING.name: QIANFAN_CODING,
    OPENCODE_GO.name: OPENCODE_GO,
    SENSENOVA.name: SENSENOVA,
}

# Backward-compatible mapping from legacy SPARK_MODE to new provider names.
SPARK_MODE_MAP = {
    "coding": XFYUN_CODING.name,
    "http": XFYUN_HTTP.name,
    "websocket": XFYUN_WEBSOCKET.name,
}


def resolve_provider_name() -> str:
    """Determine active provider from PROVIDER or legacy SPARK_MODE env vars."""
    import os

    provider = os.environ.get("PROVIDER", "").strip().lower()
    if provider:
        return provider

    spark_mode = os.environ.get("SPARK_MODE", "").strip().lower()
    if spark_mode in SPARK_MODE_MAP:
        return SPARK_MODE_MAP[spark_mode]

    return XFYUN_CODING.name


def get_provider(name: str) -> ProviderProfile:
    if name not in PROVIDERS:
        raise ValueError(
            f"Unknown provider '{name}'. Supported: {', '.join(PROVIDERS)}"
        )
    return PROVIDERS[name]
