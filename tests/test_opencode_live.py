"""Live smoke test against the OpenCode Go (experimental) endpoint.

OpenCode Go's official docs only describe the TUI ``/connect`` workflow and the
JS AI SDK — there is no documented raw HTTP/REST contract. The
``opencode-go`` provider is wired on the *convention* that
``https://opencode.ai/zen/go/v1/chat/completions`` accepts a standard
``Authorization: Bearer`` header and returns the OpenAI response shape.

This test is **opt-in**: it is skipped unless pytest is invoked with
``-m opencode_live``. It is excluded from the default suite via ``addopts``
(see ``pyproject.toml``) so it never runs alongside the hermetic tests and
never spends API quota by accident.

Run with::

    pytest -m opencode_live tests/test_opencode_live.py -v

Requires ``PROVIDER=opencode-go`` and ``API_KEY=<opencode-go-key>`` in the
environment (or a project ``.env`` that ``python-dotenv`` will load — but
note that ``load_dotenv(override=False)`` only fills missing keys). The key
is **never** hardcoded in source; if no key is configured the test is
skipped via ``pytest.skip``.

Two outcomes are accepted as legitimate:

1. **200 success** — the provider returns content + usage; we assert the
   content is non-empty and ``usage.total_tokens > 0``. This is the path
   the contract tests mock; here it proves the Bearer assumption and the
   OpenAI response shape hold against the real upstream.
2. **429 ``GoUsageLimitError``** — the workspace has hit its 5-hour quota.
   This is **not** a project bug: it means the request was authenticated,
   routed, and processed far enough for the upstream to apply its own
   business rule. We assert the error is surfaced through the project's
   normal ``ApiError`` path (via the ``review_code`` tool's
   ``success=False`` / ``error`` return) rather than crashing.

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

from coding_bridge_mcp import server as server_module


pytestmark = pytest.mark.opencode_live


# Matches the upstream ``GoUsageLimitError`` body shape:
#   {"type":"error","error":{"type":"GoUsageLimitError","message":"5-hour usage limit reached. ..."}}
_USAGE_LIMIT_RE = re.compile(r"usage limit", re.IGNORECASE)


def _load_opencode_key() -> str:
    """Resolve the OpenCode Go key from the environment first, then ``.env``.

    Order matches the opencode-go credential fallback: ``API_KEY`` →
    ``OPENCODE_API_KEY``. We read the *live* environment **before** touching
    ``.env`` so an explicitly-exported ``API_KEY`` (e.g. on the pytest command
    line) wins over any unrelated key a project ``.env`` happens to carry —
    otherwise ``load_dotenv(override=False)`` would silently substitute a key
    for a different provider and the test would 401 against opencode.
    """
    for name in ("API_KEY", "OPENCODE_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    # Only fall back to .env when the live env had nothing. override=False
    # keeps us consistent with server.py's own .env-loading semantics.
    load_dotenv(override=False)
    for name in ("API_KEY", "OPENCODE_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    pytest.skip(
        "opencode_live requires one of API_KEY / OPENCODE_API_KEY in the "
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
    """Pretty-print ``payload`` to stderr when ``-v`` is active.

    pytest shows stderr from passing tests only when ``-s`` is passed, but
    also surfaces it as a ``Captured stderr call`` block on failure. Using
    stderr (not stdout) keeps the trace separate from any test's real
    return value, matching the project's own logging convention
    (see ``logging_config.configure_logging`` and ``test_volcengine_live``).
    """
    if not verbose:
        return
    print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        file=__import__("sys").stderr,
        flush=True,
    )


def _build_opencode_settings(monkeypatch):
    """Reload server module with PROVIDER=opencode-go and a real key.

    The server reads ``_settings`` at module-load time from the environment,
    so we set the env vars first and ``reload`` the module — same trick
    ``test_opencode_contracts`` uses for ``config_module``. The lazy client
    globals are reset so the fresh ``_settings`` drives client creation.

    The key is resolved **before** any ``monkeypatch.delenv`` so an
    explicitly-exported ``API_KEY`` (pytest command line) beats any unrelated
    key a project ``.env`` carries. ``delenv`` would otherwise wipe the live
    value and let ``load_dotenv`` substitute a different provider's key.
    """
    key = _load_opencode_key()  # resolves from live env first; may pytest.skip
    for env_key in [
        "PROVIDER",
        "API_KEY",
        "OPENCODE_API_KEY",
        "OPENCODE_API_URL",
        "OPENCODE_MODEL",
        "SPARK_MODE",
        "SPARK_API_PASSWORD",
        "SPARK_API_KEY",
    ]:
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.setenv("PROVIDER", "opencode-go")
    monkeypatch.setenv("API_KEY", key)
    # Bump the timeout for the real network round-trip; the default 300s
    # is fine but the project sometimes runs with a smaller MCP_TIMEOUT_SECONDS.
    monkeypatch.setenv("MCP_TIMEOUT_SECONDS", "120")

    reload(server_module)
    # Reset the lazy client cache so the reloaded _settings is honoured.
    server_module._client = None
    server_module._client_error = None
    server_module._config_error = None
    return server_module._settings


@pytest.mark.asyncio
async def test_opencode_end_to_end_smoke(monkeypatch, request):
    """Settings → review_code tool → real OpenCode Go POST → legal outcome.

    Drives the full MCP tool pipeline (``server.review_code``) rather than
    ``HttpApiClient`` directly: this verifies the project's session/trimming/
    error-wrapping layers against the real upstream, not just the HTTP seam.

    Verbose request/response trace is printed to stderr when pytest is run
    with ``-v`` (or higher) or with ``-s``.
    """
    verbose = bool(request.config.option.verbose)
    settings = _build_opencode_settings(monkeypatch)

    # --- Local config layer checks (no network yet) ---
    assert settings is not None, "settings failed to load"
    assert settings.provider == "opencode-go"
    assert settings.mode == "http"
    assert settings.api_url == "https://opencode.ai/zen/go/v1/chat/completions"
    assert settings.default_model == "glm-5.2"
    assert settings.api_password, "API key resolved empty despite _load_opencode_key guard"

    code_sample = "def add(a, b):\n    return a + b\n"
    messages_hint = [
        {"role": "system", "content": "<code review system prompt>"},
        {"role": "user", "content": code_sample},
    ]

    _maybe_verbose(
        verbose,
        {
            "stage": "request",
            "tool": "review_code",
            "url": settings.api_url,
            "method": "POST",
            "headers": {
                "Authorization": f"Bearer {_redact_secret(settings.api_password)}",
                "Content-Type": "application/json",
            },
            "model": settings.default_model,
            "message_count": len(messages_hint),
            "payload_messages": messages_hint,
        },
    )

    # --- Real network call via the full tool pipeline ---
    result = await server_module.review_code(
        CODE=code_sample,
        cd=__import__("pathlib").Path("."),
        REQUIREMENTS="请用一句话指出这段 Python 代码的潜在问题",
    )

    _maybe_verbose(
        verbose,
        {
            "stage": "response",
            "tool": "review_code",
            "url": settings.api_url,
            "model_used": settings.default_model,
            "result": {k: v for k, v in result.items() if k != "all_messages"},
        },
    )

    # --- Branch on outcome: success OR upstream quota wall ---
    if result.get("success"):
        content = result.get("agent_messages", "")
        usage = result.get("usage")
        assert isinstance(content, str) and content.strip(), (
            f"empty content from OpenCode Go API; usage={usage}"
        )
        assert isinstance(usage, dict), f"expected usage dict, got {usage!r}"
        assert usage.get("total_tokens", 0) > 0, (
            f"expected non-zero total_tokens, got usage={usage}"
        )
        # The happy path must also populate the per-session accumulator.
        assert "SESSION_ID" in result, "review_code must return a SESSION_ID on success"
        assert "cumulative_usage" in result, "review_code must return cumulative_usage on success"
        return

    # Failure path: the only accepted failure is the upstream 5-hour quota
    # wall (HTTP 429 / GoUsageLimitError). Anything else is a real bug.
    error = str(result.get("error", ""))
    assert error, "success=False but error string is empty"
    assert "429" in error or _USAGE_LIMIT_RE.search(error), (
        "expected either success or a 429 GoUsageLimitError quota wall; "
        f"got unexpected error: {error!r}"
    )
    # On the quota path the tool must NOT claim a SESSION_ID or usage —
    # the call never produced a turn.
    assert "SESSION_ID" not in result, (
        "quota-limited call must not return a SESSION_ID; it produced no turn"
    )
