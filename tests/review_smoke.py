"""End-to-end smoke of the review_code tool.

Default mode is MOCK (FakeClient, no upstream calls). Set
``REVIEW_DEMO_LIVE=1`` to hit the real upstream via the credentials in
``.env`` (sensenova profile by default; switch via ``PROVIDER``).

Rounds:
  R1 — review_code happy path; prints the upstream call shape and the
       review verdict.
  R2 — same session, second turn; demonstrates cumulative_usage.
  R3 — HttpApiClient.call on a 429 whose body matches
       ``_NON_RETRYABLE_OVERRIDE_KEYWORDS``; verifies the override
       short-circuits retry to exactly 1 attempt.

Run from the project root::

    uv run python tests/review_smoke.py                     # mock
    REVIEW_DEMO_LIVE=1 uv run python tests/review_smoke.py  # real upstream

The filename intentionally does not start with ``test_`` so pytest does
not collect it; running the default test suite never reaches here.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

# --- pick mode BEFORE importing server modules ---------------------------
LIVE = bool(int(os.environ.get("REVIEW_DEMO_LIVE", "0")))
os.environ.setdefault("PROVIDER", "sensenova")
if not LIVE:
    os.environ.setdefault("SENSENOVA_API_KEY", "demo-only-not-a-real-key")
    os.environ.setdefault("SENSENOVA_MODEL", "glm-5.2")
    os.environ.setdefault("MCP_MAX_TOKENS", "4096")
os.environ.setdefault("MCP_MAX_CONTEXT_CHARS", "200000")

from coding_bridge_mcp import server  # noqa: E402
from coding_bridge_mcp.api_client import ApiError, HttpApiClient  # noqa: E402
from coding_bridge_mcp.config import Settings  # noqa: E402


CODE_SAMPLE = '''"""Sample code under review — intentionally has common defects."""

import sqlite3
import os

DB = "/tmp/users_demo.db"

_cache = {}

def get_user(uid):
    conn = sqlite3.connect(DB)
    row = conn.execute(f"SELECT * FROM users WHERE id = {uid}").fetchone()
    conn.close()
    _cache[uid] = row
    return row

def list_user_emails():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT id FROM users").fetchall()
    out = []
    for (uid,) in rows:
        u = get_user(uid)
        out.append(u[2])
    conn.close()
    return out

def delete_user(uid):
    os.system(f"rm -rf /tmp/user_profile_{uid}")

def safe_eval(expr):
    return eval(expr)

def init():
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INT, name TEXT, email TEXT)")
    conn.execute("INSERT INTO users VALUES (1, 'alice', 'a@example.test')")
    conn.execute("INSERT INTO users VALUES (2, 'bob',   'b@example.test')")
    conn.commit()
    conn.close()
'''

REQUIREMENTS_R1 = "重点审查：SQL 注入、命令注入、不安全 eval、资源泄漏、N+1 查询、并发安全。"
REQUIREMENTS_R2 = "现在重点关注 testability 与依赖注入：如何让这些函数可被单测覆盖？"


# --- helpers --------------------------------------------------------------


class FakeClient:
    """Drop-in for HttpApiClient; records calls and returns canned data."""

    def __init__(self, *, content=None, usage=None, raise_exc=None):
        self._content = content
        self._usage = usage
        self._raise = raise_exc
        self.calls: list[dict] = []

    async def call(self, messages, model, temperature=1.0):
        self.calls.append({
            "messages": [dict(m) for m in messages],
            "model": model,
            "temperature": temperature,
        })
        if self._raise is not None:
            raise self._raise
        return self._content, self._usage

    async def aclose(self):
        pass


def _pretty(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _redact(value):
    if not value:
        return "<unset>"
    if len(value) < 12:
        return "***"
    return f"{value[:4]}****{value[-4:]}"


def _reset_server_state():
    server._client = None
    server._client_error = None
    server._config_error = None
    server._sessions.clear()
    server._session_locks.clear()
    server._session_stats.clear()
    server._session_last_access.clear()
    server._session_users.clear()


def _smoke_settings():
    """Minimal sensenova-shaped Settings for HttpApiClient in Round 3."""
    return Settings(
        provider="sensenova",
        mode="http",
        api_url="https://token.sensenova.cn/v1/chat/completions",
        api_password="demo-only-not-a-real-key",
        default_model="glm-5.2",
        timeout_seconds=30.0,
        max_context_chars=200_000,
        max_messages=40,
        max_tokens=4096,
        proxy_mode="false",
        proxy_http=None,
        proxy_https=None,
        max_retries=3,
        retry_base_delay=0.01,
    )


# --- canned upstream responses --------------------------------------------

REVIEW_VERDICT_R1 = """\
## 审查结论：高风险 — 不建议合入

### 🔴 严重问题（必须修复）

1. **SQL 注入** — `get_user()` 第 9 行 f-string 直接拼 uid，可被 `1 OR 1=1` 越权读取。
   修复：`conn.execute("SELECT * FROM users WHERE id = ?", (uid,))`

2. **命令注入** — `delete_user()` 第 21 行 `os.system(f"rm -rf /tmp/...")` 拼外部输入。
   修复：删 `os.system`，用 `pathlib.Path(...).unlink(missing_ok=True)`。

3. **不安全 eval** — `safe_eval()` 第 24 行 `eval(expr)` 等同 RCE。
   修复：删函数；若需表达式求值，用 `ast.literal_eval`。

### 🟡 中等问题

4. **资源泄漏** — 手动 `close()`，异常路径漏连接。
   修复：`with sqlite3.connect(DB) as conn:` 上下文管理器。

5. **N+1 查询** — `list_user_emails()` 每行单独查一次。
   修复：一次性 `SELECT id, email FROM users` 后内存 zip。

### 🟢 设计层

6. **全局可变缓存** — `_cache` 并发不安全且无 TTL。
   修复：移除，或 `functools.lru_cache` + `cache_clear()` 钩子。
"""

REVIEW_VERDICT_R2 = """\
## 第二轮：可测试性

`sqlite3.connect(DB)` 在函数体内直接调用 → 无法注入测试 fixture；
`_cache` 是模块级全局 → 无法在测试间重置。

建议：把 DB 连接抽成模块顶层 `def _connect(): ...`，通过
`monkeypatch.setattr(module, "_connect", lambda: test_conn)` 注入；
`_cache` 改 `functools.lru_cache` + `cache_clear()` 钩子。
"""

USAGE_R1 = {
    "prompt_tokens": 612, "completion_tokens": 487, "total_tokens": 1099,
    "prompt_tokens_details": {"cached_tokens": 0},
}
USAGE_R2 = {
    "prompt_tokens": 720, "completion_tokens": 112, "total_tokens": 832,
    "prompt_tokens_details": {"cached_tokens": 0},
}


# --- demo -----------------------------------------------------------------


async def demo():
    if LIVE:
        # Real upstream path: only reset per-session state; the shared _client
        # is created lazily by _ensure_client on first call.
        server._client = None
        server._sessions.clear()
        server._session_locks.clear()
        server._session_stats.clear()
        server._session_last_access.clear()
        server._session_users.clear()
    else:
        _reset_server_state()

    settings = server._settings
    label = "LIVE (real HttpApiClient + .env credentials)" if LIVE else "MOCK (FakeClient, canned responses)"
    print("=" * 72)
    print(f"CONFIG ({label})")
    print("=" * 72)
    print(f"  provider           : {settings.provider}")
    print(f"  api_url            : {settings.api_url}")
    print(f"  default_model      : {settings.default_model}")
    print(f"  max_tokens (eff.)  : {settings.max_tokens}")
    print(f"  max_context_chars  : {settings.max_context_chars}")
    print(f"  timeout_seconds    : {settings.timeout_seconds}")
    print(f"  max_retries        : {settings.max_retries}")
    print(f"  api_password       : {_redact(settings.api_password)}")
    print(f"  CODE_REVIEW_SYSTEM_PROMPT ({len(server.CODE_REVIEW_SYSTEM_PROMPT)} chars):")
    for line in server.CODE_REVIEW_SYSTEM_PROMPT.splitlines():
        print(f"    | {line}")

    if LIVE:
        if not settings.api_password:
            print()
            print("  !!! .env has no SENSENOVA_API_KEY / API_KEY — aborting LIVE run.")
            return
        print("  client             : HttpApiClient(real upstream)")
    else:
        fake = FakeClient(content=REVIEW_VERDICT_R1, usage=USAGE_R1)
        server._client_factory = lambda _s: fake
        print("  client             : FakeClient(mock)")

    # ----- Round 1 --------------------------------------------------------
    sid = str(uuid.uuid4())
    user_content_r1 = f"【审查要求/上下文】\n{REQUIREMENTS_R1}\n\n【代码】\n{CODE_SAMPLE}"
    print()
    print("=" * 72)
    print("ROUND 1 — review_code (single turn, success path)")
    print("=" * 72)
    print(f"  session_id    : {sid}")
    print(f"  user_content  : {len(user_content_r1)} chars")

    result_1 = await server._execute(
        session_id=sid, user_content=user_content_r1,
        system_prompt=server.CODE_REVIEW_SYSTEM_PROMPT,
        model=settings.default_model, return_all_messages=True,
    )

    if LIVE:
        persisted = server._sessions.get(sid, [])
        sent_r1_count = len(persisted) - 1
        print()
        print("  --- upstream CALL (LIVE: reconstructed from server._sessions) ---")
        print(f"  model        : {settings.default_model}")
        print("  temperature  : 1.0")
        print(f"  messages     : {sent_r1_count} turn(s) POSTed "
              f"(session has {len(persisted)} including the reply)")
        for i, m in enumerate(persisted[:-1]):
            preview = m["content"][:80].replace("\n", " ")
            print(f"    [{i}] role={m['role']:9s} preview={preview!r}...")
        last = persisted[-1]
        print(f"    [response] assistant, {len(last['content'])} chars")
    else:
        print()
        print("  --- upstream CALL (captured by FakeClient) ---")
        call_1 = fake.calls[-1]
        print(f"  model        : {call_1['model']}")
        print(f"  temperature  : {call_1['temperature']}")
        print(f"  messages     : {len(call_1['messages'])} turn(s)")
        for i, m in enumerate(call_1["messages"]):
            preview = m["content"][:80].replace("\n", " ")
            print(f"    [{i}] role={m['role']:9s} preview={preview!r}...")

    print()
    print("  --- tool result ---")
    print(f"  success         : {result_1['success']}")
    print(f"  SESSION_ID      : {result_1['SESSION_ID']}")
    print(f"  usage           : {_pretty(result_1['usage'])}")
    print(f"  cumulative_usage: {_pretty(result_1['cumulative_usage'])}")
    print()
    print("  --- agent_messages (审查结论) ---")
    print(result_1["agent_messages"])

    # ----- Round 2 (same session) ------------------------------------------
    if LIVE:
        fake = None  # never referenced on the LIVE path
    else:
        fake._content = REVIEW_VERDICT_R2
        fake._usage = USAGE_R2

    user_content_r2 = f"【审查要求/上下文】\n{REQUIREMENTS_R2}\n\n【代码】\n{CODE_SAMPLE}"
    print()
    print("=" * 72)
    print("ROUND 2 — review_code on the SAME session (multi-turn)")
    print("=" * 72)
    print(f"  session_id    : {sid}   (reused)")

    result_2 = await server._execute(
        session_id=sid, user_content=user_content_r2,
        system_prompt=server.CODE_REVIEW_SYSTEM_PROMPT,
        model=settings.default_model, return_all_messages=True,
    )

    if LIVE:
        persisted = server._sessions.get(sid, [])
        sent_r2_count = len(persisted) - 1
        print(f"  upstream messages count: {sent_r2_count}  (was {sent_r1_count})")
        for i, m in enumerate(persisted[:-1]):
            print(f"    [{i}] role={m['role']:9s} chars={len(m['content'])}")
    else:
        call_2 = fake.calls[-1]
        print(f"  upstream messages count: {len(call_2['messages'])}  (was {len(call_1['messages'])})")
        for i, m in enumerate(call_2["messages"]):
            print(f"    [{i}] role={m['role']:9s} chars={len(m['content'])}")

    print()
    print(f"  success         : {result_2['success']}")
    print(f"  usage           : {_pretty(result_2['usage'])}")
    print(f"  cumulative_usage: {_pretty(result_2['cumulative_usage'])}")

    if not LIVE:
        print()
        print(f"  (sanity: round-1+round-2 prompt_tokens = "
              f"{USAGE_R1['prompt_tokens']} + {USAGE_R2['prompt_tokens']} = "
              f"{USAGE_R1['prompt_tokens'] + USAGE_R2['prompt_tokens']}, "
              f"cumulative says {result_2['cumulative_usage']['prompt_tokens']})")
    else:
        print()
        print("  (LIVE: cumulative comes straight from the real upstream.)")

    # ----- Round 3 — HttpApiClient on a 429 with override keyword --------
    print()
    print("=" * 72)
    print("ROUND 3 — HttpApiClient.call on a 429 with override keyword")
    print("=" * 72)
    print("  Exercises _NON_RETRYABLE_OVERRIDE_KEYWORDS: a 429 with body")
    print("  'Workspace allocated quota exceeded' must short-circuit retry")
    print(f"  to exactly 1 attempt (max_retries={settings.max_retries} otherwise).")

    call_count = 0

    async def _fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        response = MagicMock()
        response.status_code = 429
        response.headers = {}
        response.content = b""
        response.json.return_value = {
            "error": {"message": "Workspace allocated quota exceeded"}
        }
        response.text = json.dumps(response.json.return_value)
        return response

    with patch("httpx.AsyncClient") as mock_cls:
        fake_httpx = MagicMock()
        fake_httpx.__aenter__ = AsyncMock(return_value=fake_httpx)
        fake_httpx.__aexit__ = AsyncMock(return_value=None)
        fake_httpx.post = _fake_post
        mock_cls.return_value = fake_httpx

        try:
            await HttpApiClient(_smoke_settings()).call(
                [{"role": "user", "content": "ping"}], model="glm-5.2"
            )
        except ApiError as exc:
            print(f"  ApiError raised : {str(exc)[:120]}")
            print(f"  exc.retryable  : {exc.retryable}")
    print(f"  http call count : {call_count}  "
          f"(expected 1, NOT 1 + max_retries = {1 + settings.max_retries})")


if __name__ == "__main__":
    asyncio.run(demo())