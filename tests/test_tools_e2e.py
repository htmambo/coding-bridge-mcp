"""End-to-end tests for the four MCP tools exposed by ``coding_bridge_mcp.server``.

Hermetic — never hits a real provider. We monkeypatch ``_client_factory`` with a
``FakeClient`` that returns deterministic responses, then drive the tool
functions the same way an MCP host would (await the async function, inspect
its dict return).

Coverage goals:

- ``chat`` / ``review_code`` / ``review_plan`` all return ``success=True`` on
  the happy path, populate ``SESSION_ID`` / ``agent_messages`` / ``usage`` /
  ``cumulative_usage`` consistently, and pick up the right system prompt
  (``DEFAULT_SYSTEM_PROMPT`` vs code vs plan prompt).
- ``review_code`` and ``review_plan`` splice ``REQUIREMENTS`` / ``CONTEXT``
  into the user message verbatim.
- A long (>=100 lines) code sample passes through end-to-end without
  truncation by the default ``max_context_chars`` budget — the review tool
  receives the full sample, not a summary.
- ``get_token_stats`` integrates with the per-session accumulator: one
  ``review_code`` call must produce a non-zero ``total_tokens`` and be
  observable through ``get_token_stats`` for the same ``SESSION_ID``.
- Error paths: empty CODE / PLAN, missing cd are reported as
  ``success=False`` with a clear ``error`` string and never call the client.
- A >=100-char structured review result (containing the agreed-upon sections:
  风险 / 优先级 / 修改建议) survives the round-trip and is asserted on so a
  future refactor that drops the format will fail this test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import reload
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from coding_bridge_mcp import server as server_module


# ---------------------------------------------------------------------------
# Sample code (intentionally >= 100 lines to exercise long-input handling)
# ---------------------------------------------------------------------------

SAMPLE_CODE = '''\
"""Minimal user-auth API for review.

NOT production-quality: written to surface several review findings at once
(SQL injection, plaintext password comparison, missing CSRF, broad except,
information disclosure). The review tool must receive every byte.
"""
import hashlib
import hmac
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer

DB_PATH = "users.db"
SESSION_COOKIE = "sid"

def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with _db() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "id INTEGER PRIMARY KEY, "
            "name TEXT UNIQUE, "
            "pwd TEXT, "
            "role TEXT DEFAULT 'user'"
            ")"
        )

def hash_password(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()

def verify_password(plain: str, stored: str) -> bool:
    return hash_password(plain) == stored

class AuthHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode()
            data = json.loads(raw) if raw else {}
        except Exception:
            self._send_json(400, {"error": "bad request"})
            return

        if self.path == "/register":
            user = data.get("username")
            pwd = data.get("password")
            if not user or not pwd:
                self._send_json(400, {"error": "missing fields"})
                return
            with _db() as c:
                c.execute(
                    "INSERT INTO users(name, pwd) VALUES("
                    f"'{user}', '{hash_password(pwd)}'"
                    ")"
                )
            self._send_json(200, {"ok": True})
            return

        if self.path == "/login":
            user = data.get("username")
            pwd = data.get("password")
            with _db() as c:
                row = c.execute(
                    f"SELECT * FROM users WHERE name='{user}'"
                ).fetchone()
            if row and verify_password(pwd, row["pwd"]):
                self.send_header("Set-Cookie", f"{SESSION_COOKIE}={row['id']}")
                self._send_json(200, {"ok": True})
            else:
                self._send_json(401, {"error": "invalid"})
            return

        self._send_json(404, {"error": "no such route"})

    def log_message(self, fmt, *args):
        return  # silence stderr noise

def main(host="127.0.0.1", port=8000):
    init_db()
    HTTPServer((host, port), AuthHandler).serve_forever()

if __name__ == "__main__":
    main()

# Padded to ensure the sample remains >=100 lines even after refactors.
# Each blank/comment line below counts toward the line budget required by
# test_review_code_long_sample_full_round_trip.
# line  96
# line  97
# line  98
# line  99
# line 100
# line 101
# line 102
# line 103
# line 104
# line 105
'''


# A structured review with the three sections the system prompt asks for.
STRUCTURED_REVIEW = (
    "## 风险（按优先级排序）\n"
    "1. [严重] SQL 注入：register 与 login 两条路径都用 f-string 拼 SQL。\n"
    "2. [严重] 密码哈希未加盐，且使用 SHA-256，应改 Argon2/bcrypt。\n"
    "3. [中等] Cookie 未设置 HttpOnly / Secure / SameSite，可被 XSS 盗取。\n"
    "4. [低] `except Exception` 静默吞错，调试困难。\n\n"
    "## 优先级\n"
    "P0 修复 SQL 注入；P1 加盐哈希；P2 加固 Cookie；P3 细化异常。\n\n"
    "## 修改建议\n"
    "- 使用参数化查询 ``c.execute('SELECT * FROM users WHERE name=?', (user,))``。\n"
    "- 替换 ``hashlib.sha256`` 为 ``argon2-cffi`` 或 ``passlib.hash.bcrypt``。\n"
    "- 设置 ``Set-Cookie: sid=...; HttpOnly; Secure; SameSite=Lax``。\n"
)


# A second long plan document (>= 100 lines) for the plan-review path.
SAMPLE_PLAN = """\
# Project Phoenix — Q3 Migration Plan

## Background
The legacy monolith at /legacy has been running for 7 years. It owns user auth,
billing, and reporting in a single Django 1.11 process. Upstream is EOL and
security patches are no longer delivered.

## Goals
1. Decouple auth into a standalone service.
2. Move billing onto a typed event bus.
3. Reduce p95 latency on the dashboard by 40%.

## Non-goals
- Rewriting the reporting module (out of scope this quarter).
- Public API changes (consumers depend on v1 wire format).

## Proposed Architecture
- Auth service: FastAPI + Postgres + Redis sessions.
- Event bus: NATS JetStream with at-least-once delivery.
- Dashboard: React SPA hitting a new BFF that proxies legacy endpoints.

## Step-by-step Plan
1. Week 1 — Stand up the auth service skeleton, mirror the user table.
2. Week 2 — Implement login / logout / refresh endpoints behind a feature flag.
3. Week 3 — Migrate 10% of traffic to the new auth service; compare metrics.
4. Week 4 — Ramp to 100%; decommission the Django auth views.
5. Week 5 — Build the billing event bus producer in the monolith.
6. Week 6 — Stand up the consumer; replay last 7 days for backfill.
7. Week 7 — Cut billing traffic over; alert on divergence.
8. Week 8 — BFF dashboard; cache layer; remove N+1 queries.

## Risks
- Session migration: existing JWTs must remain valid for 30 days.
- Billing replay: idempotency keys are mandatory on every event.
- BFF: latency budget of 80ms; falls back to legacy on miss.

## Rollback
Each step is gated by a feature flag. Reverting the flag returns traffic to
the legacy path within one minute.

## Test & Monitoring
- Contract tests for the auth service vs legacy.
- Synthetic checks every 30s on /login and /billing.
- Dashboards: error rate, p50/p95/p99, auth-service CPU.

## Open Questions
- Who owns the event bus schema versioning policy?
- Is the BFF team OK with a 2-week budget?
"""


# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------


@dataclass
class FakeClient:
    """Drop-in replacement for ``ApiClient`` that records and replays calls.

    The test sets ``next_response`` (assistant text) and ``next_usage`` (usage
    dict). After every ``call`` the ``messages_seen`` list records the exact
    messages list passed in, so tests can assert on system-prompt selection,
    REQUIREMENTS splicing, and that long code samples survive intact.
    """

    next_response: str = "ok"
    next_usage: Dict[str, int] | None = field(
        default_factory=lambda: {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "cached_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
    )
    raise_on_call: Exception | None = None
    messages_seen: List[List[Dict[str, str]]] = field(default_factory=list)

    async def call(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 1.0,
    ) -> Tuple[str, Dict[str, Any] | None]:
        # Snapshot defensively so later in-place mutations don't poison assertions.
        self.messages_seen.append([dict(m) for m in messages])
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return self.next_response, dict(self.next_usage) if self.next_usage else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch):
    """Reload server with a clean env, install a FakeClient as the factory.

    Yields the FakeClient so tests can read messages_seen / set next_response.
    """
    monkeypatch.setenv("SPARK_MODE", "coding")
    monkeypatch.setenv("SPARK_API_PASSWORD", "fake-key")
    monkeypatch.setenv("API_KEY", "fake-key")
    monkeypatch.setenv("MCP_MAX_CONTEXT_CHARS", "200000")  # don't trim the 100-line sample
    monkeypatch.setenv("MCP_MAX_MESSAGES", "40")
    reload(server_module)

    fake = FakeClient()
    monkeypatch.setattr(server_module, "_client_factory", lambda _settings: fake)
    # Also reset any stale client/error state from previous tests.
    server_module._client = None
    server_module._client_error = None
    server_module._sessions.clear()
    server_module._session_stats.clear()
    return fake


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A real, existing directory so ``_validate_cd`` passes."""
    d = tmp_path / "ws"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# chat tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_happy_path(fake_client, workspace):
    fake_client.next_response = "你好，世界。"

    result = await server_module.chat(
        PROMPT="请用中文问好", cd=workspace, model="astron-code-latest"
    )

    assert result["success"] is True
    assert result["agent_messages"] == "你好，世界。"
    assert isinstance(result["SESSION_ID"], str) and result["SESSION_ID"]
    # System prompt must be the chat-specific one (not code/plan review prompt).
    msgs = fake_client.messages_seen[0]
    assert msgs[0]["role"] == "system"
    assert "AI 编程助手" in msgs[0]["content"]
    assert "代码审查员" not in msgs[0]["content"]
    assert "资深技术负责人" not in msgs[0]["content"]
    # User prompt lands as-is.
    assert msgs[-1] == {"role": "user", "content": "请用中文问好"}
    # Usage is normalized through _normalize_usage.
    assert result["usage"]["total_tokens"] == 30
    assert result["cumulative_usage"]["total_tokens"] == 30


@pytest.mark.asyncio
async def test_chat_rejects_empty_prompt(fake_client, workspace):
    result = await server_module.chat(PROMPT="   ", cd=workspace)
    assert result["success"] is False
    assert "PROMPT" in result["error"]
    assert fake_client.messages_seen == []  # client never called


@pytest.mark.asyncio
async def test_chat_rejects_missing_cd(fake_client):
    result = await server_module.chat(PROMPT="hi", cd=Path("/no/such/dir"))
    assert result["success"] is False
    assert "does not exist" in result["error"]
    assert fake_client.messages_seen == []


# ---------------------------------------------------------------------------
# review_code tool — the headline e2e test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_code_long_sample_full_round_trip(fake_client, workspace):
    """≥100 行样本：system prompt、REQUIREMENTS 拼接、长 code 不被裁剪、usage 累加全链路。"""
    fake_client.next_response = STRUCTURED_REVIEW

    assert len(SAMPLE_CODE.splitlines()) >= 100, (
        "fixture regression: SAMPLE_CODE must remain >=100 lines for this test"
    )

    result = await server_module.review_code(
        CODE=SAMPLE_CODE,
        cd=workspace,
        REQUIREMENTS="重点关注：SQL 注入、密码哈希、Cookie 安全、异常处理。",
        model="astron-code-latest",
    )

    # 1. Result envelope
    assert result["success"] is True
    assert result["agent_messages"] == STRUCTURED_REVIEW
    assert isinstance(result["SESSION_ID"], str) and result["SESSION_ID"]
    assert result["usage"]["total_tokens"] == 30
    assert result["cumulative_usage"]["total_tokens"] == 30

    # 2. System prompt is the CODE_REVIEW_SYSTEM_PROMPT (not chat / plan).
    msgs = fake_client.messages_seen[0]
    assert msgs[0]["role"] == "system"
    assert "代码审查员" in msgs[0]["content"]
    assert "AI 编程助手" not in msgs[0]["content"]
    assert "资深技术负责人" not in msgs[0]["content"]

    # 3. The full code sample is preserved — no truncation by _trim_messages.
    user_msg = msgs[-1]
    assert user_msg["role"] == "user"
    assert SAMPLE_CODE in user_msg["content"]

    # 4. REQUIREMENTS spliced in verbatim with the agreed marker.
    assert "【审查要求/上下文】" in user_msg["content"]
    assert "重点关注：SQL 注入" in user_msg["content"]
    assert "【代码】" in user_msg["content"]

    # 5. Structured review result carries the three sections.
    assert "风险" in result["agent_messages"]
    assert "优先级" in result["agent_messages"]
    assert "修改建议" in result["agent_messages"]
    assert len(result["agent_messages"]) >= 100, (
        "review content is too short; the format contract requires ≥100 chars"
    )


@pytest.mark.asyncio
async def test_review_code_without_requirements_drops_splice_marker(fake_client, workspace):
    """Empty REQUIREMENTS must NOT prepend the 【审查要求/上下文】 block."""
    fake_client.next_response = "ok"

    result = await server_module.review_code(CODE=SAMPLE_CODE, cd=workspace)

    assert result["success"] is True
    user_msg = fake_client.messages_seen[0][-1]
    assert user_msg["role"] == "user"
    assert "【审查要求/上下文】" not in user_msg["content"]
    assert user_msg["content"] == SAMPLE_CODE


@pytest.mark.asyncio
async def test_review_code_rejects_empty_code(fake_client, workspace):
    result = await server_module.review_code(CODE="", cd=workspace)
    assert result["success"] is False
    assert "CODE" in result["error"]
    assert fake_client.messages_seen == []


@pytest.mark.asyncio
async def test_review_code_propagates_api_error(fake_client, workspace):
    fake_client.raise_on_call = server_module.ApiError("boom")

    result = await server_module.review_code(CODE=SAMPLE_CODE, cd=workspace)

    assert result["success"] is False
    assert "boom" in result["error"]
    # On the API-error branch the response does NOT carry SESSION_ID (the
    # session is mid-flight). We still verify the session store is in a
    # coherent state by listing it: at least one session must exist with
    # system + user and NO assistant turn appended.
    assert server_module._sessions, "API error must not wipe the session store"
    sid, msgs = next(iter(server_module._sessions.items()))
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user"], (
        f"API error must not append assistant; got roles={roles}"
    )# ---------------------------------------------------------------------------
# review_plan tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_plan_happy_path(fake_client, workspace):
    fake_client.next_response = "## 优点 ...\n## 风险 ...\n## 改进建议 ..."

    result = await server_module.review_plan(
        PLAN=SAMPLE_PLAN,
        cd=workspace,
        CONTEXT="Q3 季度迁移目标。",
        model="astron-code-latest",
    )

    assert result["success"] is True
    assert "改进建议" in result["agent_messages"]
    msgs = fake_client.messages_seen[0]
    assert msgs[0]["role"] == "system"
    assert "资深技术负责人" in msgs[0]["content"]
    user_msg = msgs[-1]
    assert user_msg["role"] == "user"
    assert "【项目背景】" in user_msg["content"]
    assert "Q3 季度迁移目标" in user_msg["content"]
    assert "【计划】" in user_msg["content"]
    assert "Project Phoenix" in user_msg["content"]
    assert len(SAMPLE_PLAN.splitlines()) >= 40, (
        "fixture regression: SAMPLE_PLAN must remain a long-form document"
    )


@pytest.mark.asyncio
async def test_review_plan_rejects_empty_plan(fake_client, workspace):
    result = await server_module.review_plan(PLAN="", cd=workspace)
    assert result["success"] is False
    assert "PLAN" in result["error"]
    assert fake_client.messages_seen == []


# ---------------------------------------------------------------------------
# get_token_stats integrates with the call path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_token_stats_aggregates_across_sessions(fake_client, workspace):
    """Two reviews in different sessions → global total = sum of both."""
    fake_client.next_response = "ok"
    fake_client.next_usage = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
    }

    r1 = await server_module.review_code(CODE="a\n" * 10, cd=workspace)
    r2 = await server_module.review_code(CODE="b\n" * 10, cd=workspace)
    assert r1["success"] and r2["success"]
    assert r1["SESSION_ID"] != r2["SESSION_ID"]

    stats = await server_module.get_token_stats(cd=workspace)
    assert stats["success"] is True
    assert stats["cumulative_usage"]["total_tokens"] == 300
    assert stats["session_count"] == 2


@pytest.mark.asyncio
async def test_get_token_stats_specific_session_after_call(fake_client, workspace):
    fake_client.next_response = "ok"

    r = await server_module.review_code(CODE="x\n" * 5, cd=workspace)
    sid = r["SESSION_ID"]

    stats = await server_module.get_token_stats(cd=workspace, SESSION_ID=sid)
    assert stats["success"] is True
    assert stats["found"] is True
    assert stats["SESSION_ID"] == sid
    assert stats["cumulative_usage"]["total_tokens"] > 0


@pytest.mark.asyncio
async def test_get_token_stats_unknown_session_returns_zeros(fake_client, workspace):
    stats = await server_module.get_token_stats(
        cd=workspace, SESSION_ID="never-created"
    )
    assert stats["success"] is True
    assert stats["found"] is False
    assert stats["cumulative_usage"]["total_tokens"] == 0


@pytest.mark.asyncio
async def test_get_token_stats_rejects_missing_cd(fake_client):
    stats = await server_module.get_token_stats(cd=Path("/no/such"))
    assert stats["success"] is False
    assert "does not exist" in stats["error"]


# ---------------------------------------------------------------------------
# Cross-cutting: SESSION_ID continuation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_id_continues_conversation(fake_client, workspace):
    """Passing SESSION_ID from a prior call must reuse the same session."""
    fake_client.next_response = "first"
    r1 = await server_module.review_code(CODE="a", cd=workspace)
    sid = r1["SESSION_ID"]

    fake_client.next_response = "second"
    r2 = await server_module.review_code(CODE="b", cd=workspace, SESSION_ID=sid)
    assert r2["SESSION_ID"] == sid

    # Two system messages should NOT stack — the second call should have
    # reused the existing session (1 system + 2 user + 2 assistant = 5 msgs).
    msgs = await server_module._get_or_create_session(sid, "ignored")
    system_count = sum(1 for m in msgs if m["role"] == "system")
    assert system_count == 1
    assert len(msgs) >= 4
