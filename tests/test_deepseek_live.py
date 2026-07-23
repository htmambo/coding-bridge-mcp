"""Live smoke test against the DeepSeek official API endpoint.

This test is **opt-in**: it is skipped unless pytest is invoked with
``-m deepseek_live``. By default the rest of the suite stays hermetic
(matching the project's stated policy of "no API fees from tests").

Run with::

    pytest -m deepseek_live tests/test_deepseek_live.py -v

When ``-v`` is set the test prints a verbose, redacted trace of the live
HTTP round-trip (request payload + response body). All API keys are
redacted before printing — only the first/last 4 characters remain.

Requires ``PROVIDER=deepseek`` and ``API_KEY=<sk-...>`` in the environment
(or a project ``.env`` that ``python-dotenv`` will load — but note that
``load_dotenv(override=False)`` only fills missing keys). The key is
**never** hardcoded in source; if no key is configured the test is skipped
via ``pytest.skip``.

Two outcomes are accepted as legitimate:

1. **200 success** — content + usage returned; content non-empty, mentions
   "2", and ``usage.total_tokens > 0``. This proves the Bearer assumption and
   the OpenAI response shape hold against the real upstream.
2. **402 Insufficient Balance** — the account has no funds. This is **not** a
   project bug: the request was authenticated and routed far enough for the
   upstream to apply its own billing rule. It surfaces through the project's
   normal ``ApiError`` path and is accepted here.

Any other outcome (401/403, network error, unexpected status) is a real
failure and fails the test.
"""
from __future__ import annotations

import json
import os
import re
from importlib import reload

import pytest
from dotenv import load_dotenv

from coding_bridge_mcp import api_client as api_client_module
from coding_bridge_mcp import config as config_module


pytestmark = pytest.mark.deepseek_live


# Matches the upstream 402 balance-wall body:
#   {"error":{"message":"Insufficient Balance","type":"...","code":"..."}}
_INSUFFICIENT_BALANCE_RE = re.compile(r"insufficient balance", re.IGNORECASE)


def _load_deepseek_key() -> str:
    """Resolve the DeepSeek API key from the environment or a project ``.env``.

    Order matches the deepseek credential fallback: ``DEEPSEEK_API_KEY`` →
    ``API_KEY`` after loading ``.env`` with ``override=False``.

    Raises ``pytest.skip`` when no key is configured — the live test is opt-in
    by marker, and running it without credentials would only produce a 401.
    """
    load_dotenv(override=False)
    for name in ("DEEPSEEK_API_KEY", "API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    pytest.skip(
        "deepseek_live requires one of API_KEY / DEEPSEEK_API_KEY in the "
        "environment or .env"
    )


def _redact_secret(value: str | None) -> str:
    """Return a safe, abbreviated form of a secret for verbose logging.

    Rules:
        * ``None`` or empty        → ``"<unset>"``
        * length < 12              → ``"***"``  (too short to safely truncate)
        * otherwise                → ``"<first4>****<last4>"``

    The original value is never reconstructed from this representation.
    """
    if not value:
        return "<unset>"
    if len(value) < 12:
        return "***"
    return f"{value[:4]}****{value[-4:]}"


def _maybe_verbose(verbose: bool, payload: dict) -> None:
    """Pretty-print ``payload`` to stderr when ``-v`` is active."""
    if not verbose:
        return
    print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        file=__import__("sys").stderr,
        flush=True,
    )


def _build_deepseek_settings(monkeypatch):
    """Reload config + api_client modules with PROVIDER=deepseek.

    The key is resolved before any ``monkeypatch.delenv`` so the merged
    environment follows the Provider-specific-first priority.
    """
    key = _load_deepseek_key()  # resolves from live env first; may pytest.skip
    for env_key in [
        "PROVIDER",
        "API_KEY",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_URL",
        "DEEPSEEK_MODEL",
        "SPARK_MODE",
        "SPARK_API_KEY",
    ]:
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.setenv("PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", key)
    # Bump the timeout for the real network round-trip; deepseek-v4-pro runs in
    # thinking mode and can take a while to produce the final answer.
    monkeypatch.setenv("MCP_TIMEOUT_SECONDS", "120")

    reload(config_module)
    reload(api_client_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)
    return settings


@pytest.mark.asyncio
async def test_deepseek_end_to_end_smoke(monkeypatch, request):
    """Settings → validate → HttpApiClient → real DeepSeek POST → legal outcome.

    Verbose request/response trace is printed to stderr when pytest is run
    with ``-v`` (or higher) or with ``-s``.
    """
    verbose = bool(request.config.option.verbose)
    settings = _build_deepseek_settings(monkeypatch)

    # --- Local config layer checks (no network yet) ---
    assert settings.provider == "deepseek"
    assert settings.mode == "http"
    assert "api.deepseek.com" in settings.api_url
    assert settings.api_url.endswith("/chat/completions")
    assert settings.default_model == "deepseek-v4-pro"
    assert settings.api_password.startswith("sk-"), (
        "API key does not look like a DeepSeek key (expected sk- prefix)"
    )

    client = api_client_module.create_client(settings)
    assert isinstance(client, api_client_module.HttpApiClient)

    messages = [{"role": "user", "content": "用一句话回答：1+1=?"}]

    _maybe_verbose(
        verbose,
        {
            "stage": "request",
            "url": settings.api_url,
            "method": "POST",
            "headers": {
                "Authorization": f"Bearer {_redact_secret(settings.api_password)}",
                "Content-Type": "application/json",
            },
            "payload": {
                "model": settings.default_model,
                "messages": messages,
                "stream": False,
                "temperature": 1.0,
                "max_tokens": settings.max_tokens,
            },
        },
    )

    # --- Real network call; branch on success OR upstream billing wall ---
    ApiError = api_client_module.ApiError
    try:
        content, usage = await client.call(
            messages=messages,
            model=settings.default_model,
            temperature=1.0,
        )
    except ApiError as exc:
        # The only accepted failure is a 402 Insufficient Balance — the key
        # authenticated but the account has no funds. Anything else is a bug.
        error = str(exc)
        _maybe_verbose(verbose, {"stage": "error", "error": error})
        assert "402" in error or _INSUFFICIENT_BALANCE_RE.search(error), (
            "expected either success or a 402 Insufficient Balance wall; "
            f"got unexpected error: {error!r}"
        )
        return

    _maybe_verbose(
        verbose,
        {
            "stage": "response",
            "url": settings.api_url,
            "model_used": settings.default_model,
            "content": content,
            "usage": usage,
        },
    )

    # --- Assertions on the real response ---
    assert isinstance(content, str) and content.strip(), (
        f"empty content from DeepSeek API; usage={usage}"
    )
    assert "2" in content, (
        f"expected the answer to mention '2', got: {content!r}"
    )
    assert isinstance(usage, dict)
    assert usage.get("total_tokens", 0) > 0
