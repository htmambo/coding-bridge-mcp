"""Tests for in-memory session management."""

from importlib import reload
import asyncio
from dataclasses import replace

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


class _SequencedClient:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self.active = 0
        self.max_active = 0
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def call(self, messages, model, temperature=1.0):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.calls.append([dict(message) for message in messages])
        call_number = len(self.calls)
        if call_number == 1:
            self.first_started.set()
            await self.release_first.wait()
        await asyncio.sleep(0)
        self.active -= 1
        return f"reply-{call_number}", None

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_same_session_serializes_full_turn(small_settings, tmp_path):
    client = _SequencedClient()
    server_module._client = client
    server_module._client_error = None

    first = asyncio.create_task(
        server_module.chat(PROMPT="first", cd=tmp_path, SESSION_ID="shared")
    )
    await client.first_started.wait()
    second = asyncio.create_task(
        server_module.chat(PROMPT="second", cd=tmp_path, SESSION_ID="shared")
    )
    await asyncio.sleep(0)
    assert len(client.calls) == 1

    client.release_first.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert first_result["success"] is True
    assert second_result["success"] is True
    assert len(client.calls) == 2
    assert client.calls[0][-1]["content"] == "first"
    assert client.calls[1][-2]["content"] == "reply-1"
    assert client.calls[1][-1]["content"] == "second"


@pytest.mark.asyncio
async def test_different_sessions_remain_concurrent(small_settings, tmp_path):
    client = _SequencedClient()
    client.release_first.set()
    server_module._client = client
    server_module._client_error = None

    await asyncio.gather(
        server_module.chat(PROMPT="one", cd=tmp_path, SESSION_ID="one"),
        server_module.chat(PROMPT="two", cd=tmp_path, SESSION_ID="two"),
    )

    assert client.max_active == 2


@pytest.mark.asyncio
async def test_oversized_input_is_rejected_before_client_call(small_settings, tmp_path):
    client = _SequencedClient()
    server_module._client = client
    server_module._client_error = None

    result = await server_module.chat(
        PROMPT="x" * 101,
        cd=tmp_path,
        SESSION_ID="oversized",
    )

    assert result["success"] is False
    assert "maximum" in result["error"]
    assert client.calls == []
    assert "oversized" not in server_module._sessions


@pytest.mark.asyncio
async def test_session_ttl_and_capacity_evict_idle_state(small_settings, tmp_path):
    server_module._settings = replace(
        server_module._settings,
        session_ttl_seconds=10.0,
        max_sessions=2,
    )
    await server_module._get_or_create_session("one", "system")
    await server_module._get_or_create_session("two", "system")
    await server_module._get_or_create_session("three", "system")
    assert len(server_module._sessions) == 2
    assert "one" not in server_module._sessions

    server_module._session_last_access["two"] = 0.0
    async with server_module._sessions_lock:
        server_module._purge_sessions_locked(now=11.0)
    assert "two" not in server_module._sessions
