"""Tests for in-memory session management."""

from importlib import reload

import pytest

from coding_bridge_mcp import server as server_module


@pytest.fixture
def small_settings(monkeypatch):
    """Reload server with a tiny context limit for trimming tests."""
    monkeypatch.setenv("SPARK_MODE", "coding")
    monkeypatch.setenv("SPARK_API_KEY", "key")
    monkeypatch.setenv("SPARK_MAX_CONTEXT_CHARS", "100")
    monkeypatch.setenv("SPARK_MAX_MESSAGES", "10")
    reload(server_module)


@pytest.mark.asyncio
async def test_session_keeps_system_prompt(small_settings):
    sid = "test-session-1"
    messages = await server_module._get_or_create_session(sid, "You are a reviewer.")
    assert messages == [{"role": "system", "content": "You are a reviewer."}]

    await server_module._append_message(sid, "user", "hello")
    messages = await server_module._get_or_create_session(sid, "ignored")
    assert messages[0] == {"role": "system", "content": "You are a reviewer."}
    assert messages[-1]["role"] == "user"


@pytest.mark.asyncio
async def test_session_trims_oldest(small_settings):
    sid = "test-session-2"
    await server_module._get_or_create_session(sid, "system prompt")
    # Add several long user messages.
    for i in range(5):
        await server_module._append_message(sid, "user", f"message {i} " * 50)

    messages = await server_module._get_or_create_session(sid, "system prompt")
    # System prompt + at most a couple of recent messages due to 100-char limit.
    assert messages[0] == {"role": "system", "content": "system prompt"}
    assert len(messages) < 7
    # The oldest user message should have been dropped.
    assert not any("message 0" in m["content"] for m in messages[1:])
