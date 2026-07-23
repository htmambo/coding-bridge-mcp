# Task: 新增 商汤日日新 SenseNova Provider（`sensenova`）

**Status**: ✅ Completed (2026-07-01)
**Author**: Kimi
**Scope**: 新增一个 Provider，不影响其他 Provider 的现有行为。

---

## 1. 背景与目标

### 背景

`coding-bridge-mcp` 已支持 6 个 Provider：`xfyun-coding`、`xfyun-http`、
`xfyun-websocket`、`volcengine-coding`、`qianfan-coding`、`opencode-go`。
用户希望接入**商汤日日新 SenseNova（Token Plan，公测）** 作为第 7 个 Provider，
文档地址：https://platform.sensenova.cn/docs

### 目标

1. 新增 `sensenova` Provider，遵循现有 `ProviderProfile` 数据驱动模式；
2. 复用 `HttpApiClient`（SenseNova 走标准 OpenAI 兼容端点），**不新增协议层代码**；
3. 沿用通用 `API_KEY` 入口，凭证体验与现有 Provider 保持一致；
4. 更新文档、`.env.example`、测试与 README 表。

### 关键设计决策

| 决策点 | 结论 | 依据 |
|---|---|---|
| 接入协议 | **OpenAI 兼容**（HTTP Bearer） | 官方文档：`Authorization: Bearer sk-...`，无 JWT 签名 |
| 客户端实现 | **复用 `HttpApiClient`** | OpenAI 兼容 + 现有 `usage` 解析已覆盖 |
| Provider 名 | `sensenova` | 其套餐为通用 Token Plan（非 coding 专用），不加 `-coding` 后缀 |
| 默认端点 | `https://token.sensenova.cn/v1/chat/completions` | 官方文档（注意子域名是 `token` 而非 `api`） |
| 默认模型 | `sensenova-6.7-flash-lite` | 官方全程默认、限额最高（1500 次/5h）、256K 上下文 |
| 可选模型 | `deepseek-v4-flash` | 1M 上下文 + 思考模式，限额 500 次/5h，经 `SENSENOVA_MODEL` 切换 |
| 排除模型 | `sensenova-u1-fast` | 图像生成接口（`/v1/images/generations`），非对话模型 |
| 凭证入口 | `SENSENOVA_API_KEY` → `API_KEY` 回退 | 与其他 Provider 体验一致 |
| 端点覆盖变量 | `SENSENOVA_API_URL` | 与 `QIANFAN_API_URL` 对齐 |
| 模型覆盖变量 | `SENSENOVA_MODEL` | 与 `QIANFAN_MODEL` 对齐 |
| 上下文窗口默认值 | `96000` 字符 | 保守估计（模型实际支持 256K token），可由 `MCP_MAX_CONTEXT_CHARS` 覆盖 |
| 单次输出 token 默认 | `8192` | 与其他 Provider 一致（模型上限 65536，8192 安全） |

> **重要边界**：本次任务不创建 live 烟测脚本（`test_sensenova_live.py`）。
> 原因：仅依据公开文档确定线路契约，未提供专用测试 API Key。参考
> `test_qianfan_contracts.py` 的纯 mock 契约测试模式。

---

## 2. 改动清单

| # | 文件 | 变更类型 | 概要 |
|---|---|---|---|
| 1 | `src/coding_bridge_mcp/providers.py` | 改 | 新增 `SENSENOVA` Profile + 注册到 `PROVIDERS` |
| 2 | `tests/test_config.py` | 改 | 新增 4 个 sensenova 单测 + `clean_env` 加 `SENSENOVA_*` |
| 3 | `tests/test_sensenova_contracts.py` | 新建 | 契约 mock 测试（URL / Bearer / payload / 200 usage / 4xx error / 无 usage） |
| 4 | `.env.example` | 改 | Provider 列表、凭证回退、默认模型、专属说明块、端点覆盖段 |
| 5 | `README.md` | 改 | 简介、Provider 表、§1 凭证回退与示例、§3 Claude/Kimi JSON 示例、§5 环境变量表与默认值表 |
| 6 | `docs/Task/Archive/2026-07/SENSENOVA_PROVIDER_PLAN.md` | 新建 | 本文档 |
| 7 | `docs/Task/README.md` | 改 | 任务索引新增一行 |

> 不修改 `config.py` / `api_client.py` / `server.py` —— 现有 `ProviderProfile` 数据驱动已能覆盖 SenseNova。

---

## 3. 验收标准

- `PROVIDER=sensenova` + `API_KEY=<key>` 时，`load_settings()` 不抛异常、`validate_settings()` 通过；
- `tests/test_config.py` 与 `tests/test_sensenova_contracts.py` 全绿；
- `uv run pytest`（默认配置）全套通过；
- `uv run ruff check src tests` 无新告警；
- 没有改动 `config.py` / `api_client.py` / `server.py`，现有 6 个 Provider 行为零变化。

---

## 4. 风险评估与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| 未做真实链路验证（无测试 key） | 中 | 契约由官方文档锁定；README 注明默认值可覆盖，建议首用 curl 实测 |
| `deepseek-v4-flash` 默认开启思考模式，响应含 `reasoning_content` | 低 | 客户端只取 `choices[0].message.content`（最终答复），`reasoning_content` 被忽略，符合审查工具预期 |
| 上下文窗口默认值 `96000` 与套餐不符 | 低 | 走 `MCP_MAX_CONTEXT_CHARS` 显式覆盖；README 提示 |
| 影响其他 Provider | 极低 | 纯增量：新增 dataclass 实例 + 字典条目 |

---

## 5. 回滚方案

纯增量改动，任一处出问题可单文件 `git revert`，不影响其他 Provider 行为。

---

## 6. 备注

- 本仓库 `AGENTS.md` 要求经 `mcp__coding-bridge__review_plan` / `review_code` 审查，
  但本次执行环境未挂载该 MCP Server 工具，无法调用，已在交付说明中显式声明。
