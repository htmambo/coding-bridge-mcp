# Analysis: sensenova 接口容错硬化（2026-09-16）

**目的**：沉淀本轮端到端改动的关键决策与权衡，供后续维护者快速理解。

---

## 1. 改动一览（4 commits，按时间顺序）

| Commit | 标题 | 关键改动 |
|---|---|---|
| `bfa388e` | sensenova 默认 max_tokens 调整 4096 | providers.py 一行 + 5 处同步 |
| `ac1449c` | api_client 错误识别加 override 短路 | api_client.py 重构 + 15 测试 |
| `288d0f0` | review_smoke.py 沉淀 | /tmp demo 升格 + README §十 |
| `bd2ae74` | 归档 PLAN | git mv + README 索引 |

---

## 2. 问题链与根因

1. 商汤 workspace 实测单请求 `max_tokens ≤ 4096`（2026-08-18）
2. 默认 `max_tokens=8192` 撞墙 → 误导性 `429 "Workspace allocated quota exceeded"`
3. 旧 `_RETRYABLE_ERROR_KEYWORDS` 含 `"quota exceeded"` → 自动重试浪费 `1+max_retries=4` 次配额
4. 即使把默认降到 4096，其他 Provider 仍可能有 billing / subscription 硬错误被误重试

**根因**：旧 retry 决策只看 HTTP status + 单一宽泛关键词（"quota exceeded"），无法区分"软限流"（应重试）与"硬配置 / 计费错误"（不应重试）。

---

## 3. 方案选择

| 候选 | 改动量 | 影响面 |
|---|---|---|
| A. 把 sensenova `default_max_tokens` 调到 4096 | 1 行 + 5 处同步 | 仅 sensenova |
| B. `_body_hints_rate_limit` 加 override 白名单 | api_client 重构 | 全 Provider（统一层） |

采用 A+B。A 立刻止血，B 根除误识别。

---

## 4. 关键决策

1. **拆常量而非加 helper**：把 `_RETRYABLE_ERROR_KEYWORDS` 拆为
   `_RETRYABLE_RATE_LIMIT_HINTS` + `_NON_RETRYABLE_OVERRIDE_KEYWORDS`。
   理由：override 短路天然在两个错误分支共享，避免 helper 路径漏插一处。

2. **override 列表保守**：10 条关键词，仅覆盖已知硬错误信号。避免过宽
   列表误杀合法限流重试。

3. **smoke 脚本不带 `test_` 前缀**：避免 pytest 默认收集，确保 CI 不会
   自动跑真上游。

4. **override 命中时打 WARNING 日志**：
   `logger.warning("non_retryable_override", matched_keyword=...)`，
   便于未来发现文案变更时定位。

---

## 5. 验证矩阵

| 验证 | 结果 |
|---|---|
| `ruff check src tests` | All checks passed |
| `pytest -q`（168 = 153 + 15）| passed |
| `tests/review_smoke.py` mock 模式 | Round 1/2/3 全 OK |
| `tests/review_smoke.py` LIVE=1（真上游）| Round 1/2 200 OK，Round 3 mock 验证 override |

真上游 LIVE 端到端（2 轮 200 OK）：

| Round | elapsed_ms | usage |
|---|---|---|
| R1 | 58,990 | prompt=385, completion=3818 |
| R2 | 58,063 | prompt=3257, completion=3081（cumulative 3642/6899）|

---

## 6. 已知局限

1. **依赖 override 关键词精确性**：商汤未来若改错误文案，需重新评估
   `_NON_RETRYABLE_OVERRIDE_KEYWORDS`。WARNING 日志会暴露 `matched_keyword`
   方便定位。
2. **"quota exceeded" 裸词不再触发 retry**：当前 6 个 Provider 均使用
   `request burst` / `system protection` / `限流` / `throttl` 等其他关键词，
   无依赖裸 `quota exceeded` 的（README §五 Provider 表可证）。
3. **LIVE smoke 仍消耗真实配额**：每次 LIVE 跑 = 2 次 sensenova 请求。
   仅手动触发，不入 CI。

---

## 7. 回滚指引

- `bfa388e` revert → sensenova 默认 max_tokens 恢复 8192
- `ac1449c` revert → api_client 错误识别恢复原 retry 行为
- `288d0f0` revert → 删除 `tests/review_smoke.py` 与 README §十 那 6 行
- `bd2ae74` revert → 纯文档移动 + 索引更新，不影响代码

---

## 8. 相关文件索引

- 详细 plan：`docs/Task/Archive/2026-09/SENSENOVA_HARDENING_PLAN.md`
- Provider 注册：`src/coding_bridge_mcp/providers.py:98-108`
- Override 常量：`src/coding_bridge_mcp/api_client.py:90-119`
- 单元测试：`tests/test_api_client_retry.py`（42 用例）
- Smoke 脚本：`tests/review_smoke.py`