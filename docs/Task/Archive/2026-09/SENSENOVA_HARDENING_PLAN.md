# Task: 商汤 sensenova 接口容错硬化 + 演示脚本沉淀

**Status**: 🔄 In progress (start time: 2026-09-16)
**Author**: 果农 <htmambo@gmail.com>
**Scope**: 在已合并的 sensenova 默认 `max_tokens=4096` 修复（commit `bfa388e`）之上，
进一步硬化上游错误识别（防止"workspace allocated quota exceeded"等误导性限流
信息触发自动重试），并把 `/tmp/review_demo.py` 升格到项目内
`tests/review_smoke.py`，最后归档本任务文档。

---

## 1. 背景与目标

### 背景

`bfa388e` 已经把 sensenova 的默认 `max_tokens` 从 8192 改为 4096，避免撞上
workspace 的 4096 上限。但**根本问题仍未根治**：

- `api_client.py:92-102` 的 `_RETRYABLE_ERROR_KEYWORDS` 包含 `"quota exceeded"`。
- 商汤 workspace 在 `max_tokens>=4097` 时返回误导性 `429 Workspace allocated
  quota exceeded` —— 这不是限流，是硬配置墙。
- 当前 retry 逻辑 (`api_client.py:443`) 会把这个错误识别为 retryable，
  触发 `max_retries=3` 次重试，浪费 4 倍配额。

类似问题也存在于其他 Provider 的"配置/计费"错误（subscription expired、
余额不足、billing limit 等）—— 这些都是硬错误，不该重试。

### 目标

1. **子任务 A** —— 把"非可重试 override"显式化：body 含硬错误关键词时，
   无论 HTTP status 都不再触发自动重试。
2. **子任务 B** —— 把 `/tmp/review_demo.py` 升格到 `tests/review_smoke.py`，
   作为常驻 smoke 脚本（默认 mock，可显式切 LIVE）。
3. **子任务 C** —— 归档本任务文档，更新 `docs/Task/README.md` 索引。

---

## 2. 子任务清单

### 子任务 A：`api_client.py` 错误识别硬化

**改动文件**：
- 修改：`src/coding_bridge_mcp/api_client.py`
- 新增测试用例：`tests/test_api_client_retry.py`

**改动要点**：
- 把 `_RETRYABLE_ERROR_KEYWORDS` 重命名为 `_RETRYABLE_RATE_LIMIT_HINTS`，
  从中**移除** `"quota exceeded"`（太宽）
- 新增 `_NON_RETRYABLE_OVERRIDE_KEYWORDS`：
  ```python
  ("workspace allocated quota",
   "workspace quota",
   "insufficient balance",
   "insufficient credits",
   "余额不足",
   "欠费",
   "payment required",
   "subscription expired",
   "billing limit",
   "plan limit")
  ```
- 在 `_request_once` 的两个错误分支（非 200 分支 + provider-level error 分支）
  中：先检查 override，命中则 `retryable=False`；否则走原逻辑
- `_body_hints_rate_limit` 内部也加 override 短路（防御性）

**新增测试**：
- `test_workspace_quota_exceeded_429_not_retried`（关键：商汤场景）
- `test_workspace_quota_exceeded_5xx_not_retried`
- `test_balance_insufficient_not_retried`
- `test_subscription_expired_not_retried`
- `test_real_rate_limit_still_retried`（防回归）
- `test_bare_quota_exceeded_no_longer_retried`（关键回归守卫）

### 子任务 B：`review_smoke.py` 沉淀

**改动文件**：
- 新增：`tests/review_smoke.py`（从 `/tmp/review_demo.py` 复制，删掉 LIVE=0 默认值 setdefault 之外的不必要部分）
- 修改：`README.md` §十 增加 smoke 指引

**要点**：
- 文件名不以 `test_*.py` 开头 → pytest 默认不收集（避免 CI 误跑）
- `if __name__ == "__main__":` 守卫 + `asyncio.run(demo())`
- 保留 `LIVE=0/1` 双模 + `_redact()` 凭证 mask
- 顶部 module docstring 标明：默认 mock，LIVE 需显式 `REVIEW_DEMO_LIVE=1`
- README §十 增加一行：手动 smoke 指引 + 链接到 `tests/review_smoke.py`

### 子任务 C：归档

**改动文件**：
- 修改：`docs/Task/README.md` 索引
- 移动：本文件 → `docs/Task/Archive/2026-09/SENSENOVA_HARDENING_PLAN.md`

**Acceptance 区块填入**：
- 子任务 A 完成时间 + commit hash
- 子任务 B 完成时间 + commit hash
- 子任务 C 完成时间 + commit hash
- 外部 review verdict

---

## 3. 验收标准

| 项 | 标准 |
|---|---|
| `uv run ruff check src tests` | 无新告警 |
| `uv run pytest`（默认） | 全绿（153 + 新增 ≥ 6 用例） |
| `tests/test_api_client_retry.py` | 覆盖 override 命中/未命中两组 |
| `tests/review_smoke.py` LIVE=0 | 输出 mock 结果 |
| `tests/review_smoke.py` LIVE=1 | 真上游（可选，需用户授权） |
| 不影响其他 Provider | xfyun-coding / volcengine-coding / qianfan-coding / deepseek / opencode-go 零行为变化 |

---

## 4. 风险评估与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| override 关键词误判，错过真正可重试的限流 | 中 | 列表保守：仅包含商汤已知的硬错误信号 + 通用 billing/subscription 信号；未来发现 Provider 误报再补 |
| 子任务 A 现有测试出现回归 | 低 | 新增 `test_real_rate_limit_still_retried` 防回归；旧"quota exceeded"用例（若有）改用 "rate limit" |
| 子任务 B 进入 CI 触发真上游 | 中 | LIVE=0 默认；文件名非 `test_*.py` 模式，pytest 默认不收集 |
| 子任务 B 凭证泄露 | 中 | `_redact()` mask；不 print `.env` 内容 |
| 多文件改动引入回归 | 中 | ruff + 153 个原有测试做兜底 |

---

## 5. 回滚方案

- 子任务 A：单文件 revert `api_client.py` 即可恢复原 retry 行为
- 子任务 B：删除 `tests/review_smoke.py` 与 README 那一行
- 子任务 C：纯文档移动 + 索引更新，不影响代码

---

## 6. Acceptance / Runtime Decisions

- 子任务 A 完成时间 / commit hash：2026-09-16 / `ac1449c`
  (`fix(provider): api_client 错误识别加非可重试 override 短路`)
- 子任务 B 完成时间 / commit hash：2026-09-16 / `288d0f0`
  (`chore(tests): 沉淀 review demo 为 tests/review_smoke.py 常驻 smoke 脚本`)
- 子任务 C 完成时间 / commit hash：2026-09-16 / 本 commit
  (`docs(task): 归档 SENSENOVA_HARDENING_PLAN 到 Archive/2026-09`)
- 外部 review verdict：（见 § External Review Opinion）

### Runtime Decisions

- 子任务 A：直接修改 `_RETRYABLE_ERROR_KEYWORDS` 拆分为 `_RETRYABLE_RATE_LIMIT_HINTS`
  + `_NON_RETRYABLE_OVERRIDE_KEYWORDS`，而非新增独立过滤层。理由：拆常量比新加
  helper 更小改动，且 helper 路径在两个错误分支都要插入，容易漏一处；常量拆分天然
  在两个分支共享短路逻辑。
- 子任务 B：放在 `tests/review_smoke.py`（根目录下）而非 `tests/smoke/` 子目录。
  理由：当前 tests/ 目录扁平，新增子目录会让 pytest 收集行为复杂化；保持单文件
  + README 标注的方式足够。
- 子任务 C：保留单一 PLAN 文档而非拆 3 个。理由：单一文档便于追踪完整上下文，
  3 个子任务彼此依赖（子任务 A 是 B 的 Round 3 内容）。

---

## 7. External Review Opinion

**Round 1/5 · provider=coding-bridge · SESSION_ID=fdf85f2b-a193-40bb-81bd-f8e7963d1882**
**Verdict: APPROVED**（4 minor suggestions 全部采纳，纳入实施）

采纳的 4 条建议：

1. **大小写 / 空格鲁棒性**：`api_client._flatten_body_text` 已经 `.lower()`
   后再 `kw in text`，天然大小写不敏感；现有子串匹配容忍空格。补 1 个测试
   `test_workspace_quota_exceeded_uppercase_and_spacing_not_retried`。
2. **JSON 嵌套覆盖**：`_flatten_body_text` 现有递归遍历 dict/list 深度 3，
   已覆盖 `{"error": {"message": "..."}}` 嵌套结构。补 1 个测试
   `test_workspace_quota_deeply_nested_not_retried` 锁定契约。
3. **`"quota exceeded"` 移除安全性**：现有 Provider (xfyun-coding /
   volcengine-coding / qianfan-coding / deepseek / opencode-go) 的真实限流
   信号用的是 `request burst` / `system protection` / `限流` / `throttl` 等，
   不依赖裸 `quota exceeded`（README 注释明确 qianfan 用 burst protection）。
   所以删除安全。补 1 个测试 `test_bare_quota_exceeded_does_not_retry`
   锁定行为。
4. **override 命中日志**：在 `_request_once` 的非 200 分支命中 override 时，
   调 `logger.warning("non_retryable_override", provider=..., keyword=...)`，
   便于未来发现文案变更。

实际子任务 A 测试用例数从 6 → **9**：原 6 + 上 3 条鲁棒性测试。