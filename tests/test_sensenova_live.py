"""Live smoke test against the SenseNova (商汤日日新) Token Plan endpoint.

This test is **opt-in**: it is skipped unless pytest is invoked with
``-m sensenova_live``. By default the rest of the suite stays hermetic
(matching the project's stated policy of "no API fees from tests").

Run with::

    pytest -m sensenova_live tests/test_sensenova_live.py -v -s

When ``-v`` / ``-s`` is set the test prints a verbose, redacted trace of
the live HTTP round-trip (request payload + response body). All API keys
are redacted before printing — only the first/last 4 characters remain.

Requires ``PROVIDER=sensenova`` and ``API_KEY=<sensenova-key>`` in the
environment (or a project ``.env`` that ``python-dotenv`` will load —
``load_dotenv(override=False)`` only fills missing keys). The key is
**never** hardcoded in source; if no key is configured the test is
skipped via ``pytest.skip``.

The request uses the SENSENOVA profile's default model ``glm-5.2``, which
is confirmed to be served by the Token Plan (verified via
``GET /v1/models`` on 2026-08-18, alongside ``deepseek-v4-flash`` and the
``sensenova-*-flash-lite`` models). The HttpApiClient does not validate
the model name client-side; it just passes the string through to the
upstream.

Note on ``max_tokens``: SenseNova workspaces enforce a per-request
``max_tokens`` cap. On 2026-08-18 the cap was observed to be exactly 4096
— requests with ``max_tokens <= 4096`` return 200, while ``>= 4097`` are
rejected with a misleading ``429 Workspace allocated quota exceeded``
even when the console shows quota remaining. The profile default of 8192
would hit that wall, so this test pins ``MCP_MAX_TOKENS=4096``.

The only accepted outcome is **200 success** — content + usage returned;
content non-empty, mentions "2", and ``usage.total_tokens > 0``. Proves
the Bearer assumption and the OpenAI response shape hold against the real
upstream with the profile default model. Any ``ApiError`` (401/403/4xx/
5xx) or network error is a real failure and fails the test.
"""

from __future__ import annotations

import json
import os
from importlib import reload

import pytest
from dotenv import load_dotenv

from coding_bridge_mcp import api_client as api_client_module
from coding_bridge_mcp import config as config_module


pytestmark = pytest.mark.sensenova_live


def _load_sensenova_key() -> str:
    """Resolve the SenseNova API key from the environment or a project ``.env``.

    Order matches the sensenova credential fallback: ``SENSENOVA_API_KEY`` →
    ``API_KEY`` after loading ``.env`` with ``override=False``.

    Raises ``pytest.skip`` when no key is configured — the live test is opt-in
    by marker, and running it without credentials would only produce a 401.
    """
    load_dotenv(override=False)
    for name in ("SENSENOVA_API_KEY", "API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    pytest.skip(
        "sensenova_live requires one of API_KEY / SENSENOVA_API_KEY in the "
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
    """Pretty-print ``payload`` to stderr when ``-v`` / ``-s`` is active."""
    if not verbose:
        return
    print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        file=__import__("sys").stderr,
        flush=True,
    )


def _build_sensenova_settings(monkeypatch):
    """Reload config + api_client modules with PROVIDER=sensenova.

    The key is resolved before any ``monkeypatch.delenv`` so the merged
    environment follows the Provider-specific-first priority. No model
    override is set: the test exercises the profile default (``glm-5.2``).
    """
    key = _load_sensenova_key()  # resolves from live env first; may pytest.skip
    for env_key in [
        "PROVIDER",
        "API_KEY",
        "SENSENOVA_API_KEY",
        "SENSENOVA_API_URL",
        "SENSENOVA_MODEL",
        "SPARK_MODE",
        "SPARK_API_KEY",
    ]:
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.setenv("PROVIDER", "sensenova")
    monkeypatch.setenv("SENSENOVA_API_KEY", key)
    # SenseNova workspaces enforce a per-request max_tokens cap (observed
    # exactly 4096 on 2026-08-18: <=4096 → 200, >=4097 → a misleading
    # 429 "Workspace allocated quota exceeded"). The profile default of
    # 8192 would hit that wall, so pin the live test below the cap.
    monkeypatch.setenv("MCP_MAX_TOKENS", "4096")
    # Bump the timeout for the real network round-trip.
    monkeypatch.setenv("MCP_TIMEOUT_SECONDS", "120")

    reload(config_module)
    reload(api_client_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)
    return settings


@pytest.mark.asyncio
async def test_sensenova_glm52_end_to_end_smoke(monkeypatch, request):
    """Settings → validate → HttpApiClient → real SenseNova POST → 200 success.

    Drives the live HTTP layer against the documented Token Plan endpoint
    (``https://token.sensenova.cn/v1/chat/completions``) with the profile
    default model ``glm-5.2``. Since that model is confirmed to be served by
    the upstream, the only legal outcome is a 200 success; any error is a
    real bug.

    Verbose request/response trace is printed to stderr when pytest is run
    with ``-v`` (or higher) or with ``-s``.
    """
    verbose = bool(request.config.option.verbose)
    settings = _build_sensenova_settings(monkeypatch)

    # --- Local config layer checks (no network yet) ---
    assert settings.provider == "sensenova"
    assert settings.mode == "http"
    assert settings.api_url == "https://token.sensenova.cn/v1/chat/completions"
    assert settings.default_model == "glm-5.2", (
        "SENSENOVA profile default model drifted; "
        f"expected 'glm-5.2', got {settings.default_model!r}"
    )
    assert settings.api_password, "API key resolved empty despite _load_sensenova_key guard"

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

    # --- Real network call; the only legal outcome is success ---
    content, usage = await client.call(
        messages=messages,
        model=settings.default_model,
        temperature=1.0,
    )

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
        f"empty content from SenseNova API; usage={usage}"
    )
    assert "2" in content, (
        f"expected the answer to mention '2', got: {content!r}"
    )
    assert isinstance(usage, dict)
    assert usage.get("total_tokens", 0) > 0
