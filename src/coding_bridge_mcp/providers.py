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
    api_key_env_vars=["SPARK_API_PASSWORD", "SPARK_API_KEY"],
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
    api_key_env_vars=["SPARK_API_PASSWORD", "SPARK_API_KEY"],
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
    api_key_env_vars=["VOLCENGINE_API_KEY", "ARK_API_KEY"],
    api_url_env_vars=["VOLCENGINE_API_URL", "ARK_API_URL"],
    model_env_vars=["VOLCENGINE_MODEL", "ARK_MODEL", "SPARK_DEFAULT_MODEL"],
)

PROVIDERS = {
    XFYUN_CODING.name: XFYUN_CODING,
    XFYUN_HTTP.name: XFYUN_HTTP,
    XFYUN_WEBSOCKET.name: XFYUN_WEBSOCKET,
    VOLCENGINE_CODING.name: VOLCENGINE_CODING,
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
