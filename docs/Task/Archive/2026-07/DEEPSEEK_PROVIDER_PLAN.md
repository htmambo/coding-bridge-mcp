# Task: 新增 DeepSeek 官方 API Provider（`deepseek`）

**Status**: ✅ Completed (2026-07-01)
**Author**: Kimi
**Scope**: 新增一个 Provider，不影响其他 Provider 的现有行为。

---

## 1. 背景与目标

### 背景

`coding-bridge-mcp` 已支持 7 个 Provider：`xfyun-coding`、`xfyun-http`、
`xfyun-websocket`、`volcengine-coding`、`qianfan-coding`、`opencode-go`、
`sensenova`。用户希望接入 **DeepSeek 官方 API** 作为第 8 个 Provider，
文档地址：https://api-docs.deepseek.com/

### 目标

1. 新增 `deepseek` Provider，遵循现有 `ProviderProfile` 数据驱动模式；
2. 复用 `HttpApiClient`（DeepSeek 走标准 OpenAI 兼容端点），**不新增协议层代码**；
3. 沿用通用 `API_KEY` 入口，凭证体验与现有 Provider 保持一致；
4. 更新文档、`.env.example`、测试与 README 表；
5. 因本次提供了真实测试 key，额外补一个 opt-in live 冒烟测试并做真实链路验证。

### 关键设计决策

| 决策点 | 结论 | 依据 |
|---|---|---|
| 接入协议 | **OpenAI 兼容**（HTTP Bearer） | 官方文档：`Authorization: Bearer sk-...`，OpenAI 格式 |
| 客户端实现 | **复用 `HttpApiClient`** | OpenAI 兼容 + 现有 `usage` 解析已覆盖 |
| Provider 名 | `deepseek` | 通用官方 API（非 coding 专用套餐），不加 `-coding` 后缀，对齐 `sensenova` |
| 默认端点 | `https://api.deepseek.com/chat/completions` | 官方文档 curl 示例（base_url `https://api.deepseek.com`） |
| 默认模型 | `deepseek-v4-pro` | 用户指定（思考模式，审查质量更高） |
| 可选模型 | `deepseek-v4-flash` | 更快更省 token，经 `DEEPSEEK_MODEL` 切换 |
| 废弃模型 | `deepseek-chat` / `deepseek-reasoner` | 2026-07-24 废弃，分别对应 v4-flash 非思考 / 思考模式 |
| 凭证入口 | `DEEPSEEK_API_KEY` → `API_KEY` 回退 | 与其他 Provider 体验一致 |
| 端点覆盖变量 | `DEEPSEEK_API_URL` | 与 `SENSENOVA_API_URL` 对齐 |
| 模型覆盖变量 | `DEEPSEEK_MODEL` | 与 `SENSENOVA_MODEL` 对齐 |
| 上下文窗口默认值 | `96000` 字符 | 保守估计，可由 `MCP_MAX_CONTEXT_CHARS` 覆盖 |
| 单次输出 token 默认 | `8192` | 与其他 Provider 一致 |

> **重要边界**：`deepseek-v4-pro` 默认以思考模式运行，响应含 `reasoning_content`
> 字段。`HttpApiClient` 只取 `choices[0].message.content`（最终答复），
> `reasoning_content` 被忽略——符合审查工具预期。

---

## 2. 改动清单

| # | 文件 | 变更类型 | 概要 |
|---|---|---|---|
| 1 | `src/coding_bridge_mcp/providers.py` | 改 | 新增 `DEEPSEEK` Profile + 注册到 `PROVIDERS` |
| 2 | `tests/test_config.py` | 改 | 新增 4 个 deepseek 单测 + `clean_env` 加 `DEEPSEEK_*` |
| 3 | `tests/test_deepseek_contracts.py` | 新建 | 契约 mock 测试（URL / Bearer / payload / reasoning / 200 usage / 4xx error / 无 usage） |
| 4 | `tests/test_deepseek_live.py` | 新建 | opt-in live 冒烟测试（marker `deepseek_live`，默认不跑） |
| 5 | `pyproject.toml` | 改 | 注册 `deepseek_live` marker + 加入 `addopts` 默认排除 |
| 6 | `.env.example` | 改 | Provider 列表、凭证回退、默认模型、专属说明块、端点覆盖段 |
| 7 | `README.md` | 改 | 简介、Provider 表、§1 凭证回退与示例、§3 Claude/Kimi JSON 示例、§5 环境变量表与默认值表 |
| 8 | `docs/Task/Archive/2026-07/DEEPSEEK_PROVIDER_PLAN.md` | 新建 | 本文档 |
| 9 | `docs/Task/README.md` | 改 | 任务索引新增一行 |

> 不修改 `config.py` / `api_client.py` / `server.py` / `cli.py` —— 现有
> `ProviderProfile` 数据驱动已能覆盖 DeepSeek。

---

## 3. 验收标准

- `PROVIDER=deepseek` + `API_KEY=<key>` 时，`load_settings()` 不抛异常、`validate_settings()` 通过；
- `tests/test_config.py` 与 `tests/test_deepseek_contracts.py` 全绿；
- `uv run pytest`（默认配置，排除 live）全套通过；
- `uv run ruff check src tests` 无新告警；
- 没有改动 `config.py` / `api_client.py` / `server.py`，现有 7 个 Provider 行为零变化；
- live 冒烟测试 `pytest -m deepseek_live tests/test_deepseek_live.py` 用真实 key 通过（200 成功或 402 余额墙均视为合法）。

---

## 4. 风险评估与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| `deepseek-v4-pro` 思考模式响应含 `reasoning_content` | 低 | 客户端只取 `content`（最终答复），`reasoning_content` 被忽略 |
| 默认模型日后名称变更（旧名 2026-07-24 废弃） | 低 | 默认用新名 `deepseek-v4-pro`；可由 `DEEPSEEK_MODEL` 覆盖 |
| 上下文窗口默认值 `96000` 与真实上限不符 | 低 | 走 `MCP_MAX_CONTEXT_CHARS` 显式覆盖；README 提示 |
| 影响其他 Provider | 极低 | 纯增量：新增 dataclass 实例 + 字典条目 |

---

## 5. 回滚方案

纯增量改动，任一处出问题可单文件 `git revert`，不影响其他 Provider 行为。

---

## 6. 备注

- 本仓库 `AGENTS.md` 要求经 `mcp__coding-bridge__review_plan` / `review_code` 审查，
  但本次执行环境未挂载该 MCP Server 工具（工具列表无 `mcp__coding-bridge__*`），
  无法调用，已在交付说明中显式声明。
- 测试 key 仅用于本地 live 验证（通过环境变量传入），**未写入任何提交文件**。
