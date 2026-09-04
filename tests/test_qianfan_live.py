"""Live smoke test against the Baidu Qianfan Coding Plan endpoint.

This test is **opt-in**: it is skipped unless pytest is invoked with
``-m qianfan_live``. By default the rest of the suite stays hermetic
(matching the project's stated policy of "no API fees from tests").

Run with::

    pytest -m qianfan_live tests/test_qianfan_live.py -v -s

When ``-v`` / ``-s`` is set the test prints a verbose, redacted trace of
the live HTTP round-trip (request payload + response body). All API keys
are redacted before printing — only the first/last 4 characters remain.

Requires ``PROVIDER=qianfan-coding`` and ``QIANFAN_API_KEY=<bce-v3/...>``
in the environment (or a project ``.env`` that ``python-dotenv`` will load —
``load_dotenv(override=False)`` only fills missing keys). The key is
**never** hardcoded in source; if no key is configured the test is skipped
via ``pytest.skip``.

The test uses ``settings.default_model`` rather than pinning a specific
model name: qianfan Coding Plan serves ``glm-5.2`` (profile default) plus
overrides like ``glm-5.3-flash`` set via ``QIANFAN_MODEL``. Pinning a name
would force every operator to re-edit this test whenever they switch
models. The model string is asserted only to be non-empty — drift
detection between profile and runtime is left to the hermetic contract
tests (``test_qianfan_contracts``).

The only accepted outcome is **200 success** — content + usage returned;
content non-empty, mentions "2", and ``usage.total_tokens > 0``. Proves
the ``Authorization: Bearer bce-v3/...`` assumption and the OpenAI
response shape hold against the real upstream with the profile default
(or env-overridden) model. Any ``ApiError`` (401/403/4xx/5xx) or network
error is a real failure and fails the test.
"""

from __future__ import annotations

import json
import os
from importlib import reload

import pytest
from dotenv import load_dotenv

from coding_bridge_mcp import api_client as api_client_module
from coding_bridge_mcp import config as config_module


pytestmark = pytest.mark.qianfan_live


def _load_qianfan_key() -> str:
    """Resolve the Qianfan API key from the environment or a project ``.env``.

    Order matches the qianfan-coding credential fallback: ``QIANFAN_API_KEY`` →
    ``API_KEY`` after loading ``.env`` with ``override=False``.

    Raises ``pytest.skip`` when no key is configured — the live test is opt-in
    by marker, and running it without credentials would only produce a 401.
    """
    load_dotenv(override=False)
    for name in ("QIANFAN_API_KEY", "API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    pytest.skip(
        "qianfan_live requires one of API_KEY / QIANFAN_API_KEY in the "
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


def _build_qianfan_settings(monkeypatch):
    """Reload config + api_client modules with PROVIDER=qianfan-coding.

    The key is resolved before any ``monkeypatch.delenv`` so the merged
    environment follows the Provider-specific-first priority. No model
    override is set: the test exercises whatever
    ``settings.default_model`` resolves to (profile default or
    ``QIANFAN_MODEL`` env override).
    """
    key = _load_qianfan_key()  # resolves from live env first; may pytest.skip
    for env_key in [
        "PROVIDER",
        "API_KEY",
        "QIANFAN_API_KEY",
        "QIANFAN_API_URL",
        "QIANFAN_MODEL",
        "SPARK_MODE",
        "SPARK_API_KEY",
    ]:
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.setenv("PROVIDER", "qianfan-coding")
    monkeypatch.setenv("QIANFAN_API_KEY", key)
    # Bump the timeout for the real network round-trip; qianfan Coding Plan
    # observed ~5s on first call, plenty of headroom under 120s.
    monkeypatch.setenv("MCP_TIMEOUT_SECONDS", "120")

    reload(config_module)
    reload(api_client_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)
    return settings


@pytest.mark.asyncio
async def test_qianfan_end_to_end_smoke(monkeypatch, request):
    """Settings → validate → HttpApiClient → real Qianfan POST → 200 success.

    Drives the live HTTP layer against the documented Coding Plan endpoint
    (``https://qianfan.baidubce.com/v2/tokenplan/personal/chat/completions``)
    with whatever model ``settings.default_model`` resolves to. Since the
    profile default ``glm-5.2`` (and the ``QIANFAN_MODEL`` overrides like
    ``glm-5.3-flash`` confirmed via the live script on 2026-09-05) are
    served by the upstream, the only legal outcome is a 200 success; any
    error is a real bug.

    Verbose request/response trace is printed to stderr when pytest is run
    with ``-v`` (or higher) or with ``-s``.
    """
    verbose = bool(request.config.option.verbose)
    settings = _build_qianfan_settings(monkeypatch)

    # --- Local config layer checks (no network yet) ---
    assert settings.provider == "qianfan-coding"
    assert settings.mode == "http"
    assert settings.api_url == (
        "https://qianfan.baidubce.com/v2/tokenplan/personal/chat/completions"
    )
    assert settings.default_model, (
        "settings.default_model resolved empty; check QIANFAN_MODEL and the "
        "QIANFAN_CODING profile in providers.py"
    )
    assert settings.api_password, "API key resolved empty despite _load_qianfan_key guard"

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
        f"empty content from Qianfan API; usage={usage}"
    )
    assert "2" in content, (
        f"expected the answer to mention '2', got: {content!r}"
    )
    assert isinstance(usage, dict)
    assert usage.get("total_tokens", 0) > 0, (
        f"expected total_tokens > 0, got usage={usage}"
    )
