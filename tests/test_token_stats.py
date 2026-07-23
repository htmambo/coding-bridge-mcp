"""Tests for the get_token_stats tool and per-session usage accumulation."""

from importlib import reload

import pytest

from coding_bridge_mcp import server as server_module


@pytest.fixture
def fresh_server(monkeypatch):
    """Reload server with clean session/state dictionaries."""
    monkeypatch.setenv("SPARK_MODE", "coding")
    monkeypatch.setenv("SPARK_API_KEY", "key")
    reload(server_module)
    # Reset module-level state in case other tests touched it.
    server_module._sessions.clear()
    server_module._session_stats.clear()
    yield


@pytest.mark.asyncio
async def test_accumulate_stats_sums_each_field(fresh_server):
    sid = "sess-1"
    await server_module._accumulate_stats(
        sid,
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_tokens": 3,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    )
    await server_module._accumulate_stats(
        sid,
        {
            "prompt_tokens": 20,
            "completion_tokens": 7,
            "total_tokens": 27,
            "cached_tokens": 0,
            "cache_creation_input_tokens": 1,
            "cache_read_input_tokens": 2,
        },
    )

    stats = server_module._session_stats[sid]
    assert stats["prompt_tokens"] == 30
    assert stats["completion_tokens"] == 12
    assert stats["total_tokens"] == 42
    assert stats["cached_tokens"] == 3
    assert stats["cache_creation_input_tokens"] == 1
    assert stats["cache_read_input_tokens"] == 2


@pytest.mark.asyncio
async def test_accumulate_stats_ignores_none(fresh_server):
    await server_module._accumulate_stats("sess-2", None)
    assert server_module._session_stats == {}


@pytest.mark.asyncio
async def test_aggregate_stats_sums_across_sessions(fresh_server):
    await server_module._accumulate_stats(
        "a",
        {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    )
    await server_module._accumulate_stats(
        "b",
        {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )
    total = server_module._aggregate_stats(list(server_module._session_stats.values()))
    assert total["prompt_tokens"] == 11
    assert total["completion_tokens"] == 22
    assert total["total_tokens"] == 33


@pytest.mark.asyncio
async def test_get_token_stats_global(fresh_server, tmp_path):
    await server_module._accumulate_stats(
        "x",
        {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
    )
    await server_module._accumulate_stats(
        "y",
        {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
    )

    result = await server_module.get_token_stats(cd=tmp_path)
    assert result["success"] is True
    assert result["session_count"] == 2
    assert result["cumulative_usage"]["prompt_tokens"] == 55
    assert result["cumulative_usage"]["completion_tokens"] == 11
    assert result["sessions"]["x"]["total_tokens"] == 6
    assert result["sessions"]["y"]["total_tokens"] == 60


@pytest.mark.asyncio
async def test_get_token_stats_specific_session(fresh_server, tmp_path):
    await server_module._accumulate_stats(
        "only",
        {"prompt_tokens": 7, "completion_tokens": 8, "total_tokens": 15},
    )

    result = await server_module.get_token_stats(
        cd=tmp_path, SESSION_ID="only"
    )
    assert result["success"] is True
    assert result["found"] is True
    assert result["cumulative_usage"]["total_tokens"] == 15


@pytest.mark.asyncio
async def test_get_token_stats_unknown_session_returns_zeros(fresh_server, tmp_path):
    result = await server_module.get_token_stats(
        cd=tmp_path, SESSION_ID="ghost"
    )
    assert result["success"] is True
    assert result["found"] is False
    assert result["cumulative_usage"]["total_tokens"] == 0


@pytest.mark.asyncio
async def test_get_token_stats_rejects_missing_cd(fresh_server, tmp_path):
    bogus = tmp_path / "does-not-exist"
    result = await server_module.get_token_stats(cd=bogus)
    assert result["success"] is False
    assert "does not exist" in result["error"]
