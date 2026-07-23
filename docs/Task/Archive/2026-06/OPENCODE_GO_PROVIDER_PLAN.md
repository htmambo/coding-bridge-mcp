# Task: 新增 OpenCode Go Provider（`opencode-go`）

**Status**: ✅ Completed (completion time: 2026-06-30)
**Author**: Claude
**Scope**: 新增一个 Provider，不影响其他 Provider 的现有行为。

---

## 1. 背景与目标

### 背景

`coding-bridge-mcp` 当前已支持 5 个 Provider：

- `xfyun-coding`（讯飞星辰 MaaS Coding Plan，默认）
- `xfyun-http`（讯飞星火通用 OpenAI 兼容）
- `xfyun-websocket`（讯飞星火原生 WebSocket）
- `volcengine-coding`（火山方舟 Coding Plan 个人版）
- `qianfan-coding`（百度智能云千帆 Coding Plan）

用户希望接入 **OpenCode Go**（OpenCode 的 Go 订阅，聚合多家模型）作为第 6 个 Provider。

### OpenCode Go 关键事实（文档实读，来源 https://opencode.ai/docs/zh-cn/go/）

| 维度 | 事实 |
|---|---|
| 协议分两路 | GLM/Kimi/DeepSeek/MiMo 走 **OpenAI 兼容**；MiniMax/Qwen 走 **Anthropic 兼容** |
| OpenAI 兼容端点 | `https://opencode.ai/zen/go/v1/chat/completions`（文档明确） |
| OpenAI 兼容模型 ID | `glm-5.2` / `glm-5.1` / `kimi-k2.7-code` / `kimi-k2.6` / `deepseek-v4-pro` / `deepseek-v4-flash` / `mimo-v2.5` / `mimo-v2.5-pro` |
| 默认模型 | `glm-5.2`（用户指定，文档实读确认大小写与连字符） |
| 认证 | 文档仅描述 TUI `/connect` 与 JS AI SDK 用法，**未给出直接 HTTP/REST 调用契约**（无 curl、无 header 规范） |
| 额度 | 美元配额制：每 5h $12 / 周 $30 / 月 $60（区别于讯飞/火山的"请求次数限制"） |

### 目标

1. 新增 `opencode-go` Provider，遵循现有 `ProviderProfile` 数据驱动模式；
2. 复用 `HttpApiClient`（OpenAI 兼容子集），**不新增协议层代码**；
3. 沿用通用 `API_KEY` 入口，凭证体验与现有 Provider 保持一致；
4. 更新文档、`.env.example`、测试与 README 表。

### 关键设计决策

| 决策点 | 结论 | 依据 |
|---|---|---|
| 接入协议 | **OpenAI 兼容**（HTTP Bearer） | 仅 OpenAI 兼容子集可复用 `HttpApiClient`；Anthropic 子集（MiniMax/Qwen）首期不接 |
| 客户端实现 | **复用 `HttpApiClient`** | OpenAI 兼容 + 现有 `usage` 解析已覆盖 |
| Provider 名 | `opencode-go` | 贴合品牌（文档模型 ID 前缀即 `opencode-go/<model>`）；非传统 Coding Plan 套餐，不套 `-coding` 后缀 |
| 默认端点 | `https://opencode.ai/zen/go/v1/chat/completions` | 文档实读 |
| 默认模型 | `glm-5.2` | 用户指定 + 文档实读确认 |
| 凭证入口 | `OPENCODE_API_KEY` → `API_KEY` 回退 | 与 `qianfan-coding` 体验一致 |
| 端点覆盖变量 | `OPENCODE_API_URL` | 与 `QIANFAN_API_URL` 对齐 |
| 模型覆盖变量 | `OPENCODE_MODEL` | 与 `QIANFAN_MODEL` 对齐 |
| 上下文窗口默认值 | `96000` | 文档未给出 GLM-5.2 精确上下文长度；取保守中间值，README 注明可由 `MCP_MAX_CONTEXT_CHARS` 覆盖 |
| 单次输出 token 默认 | `8192` | 与 `xfyun-coding` / `volcengine-coding` / `qianfan-coding` 一致 |

> **重要边界**：本次任务不创建 live 烟测脚本（`test_opencode_live.py`）。
> 原因：用户未提供 Go 订阅 API Key，且认证头契约未被官方文档明确。参考
> `test_volcengine_live.py` 的 opt-in 模式，留待后续有 key 时再补。

---

## 2. 改动清单

| # | 文件 | 变更类型 | 概要 |
|---|---|---|---|
| 1 | `src/coding_bridge_mcp/providers.py` | 改 | 新增 `OPENCODE_GO` Profile + 注册到 `PROVIDERS` |
| 2 | `tests/test_config.py` | 改 | 扩 `clean_env` fixture 加 `OPENCODE_*` 清理；新增默认值 / 通用 API_KEY / first-match-wins 三个单测 |
| 3 | `tests/test_opencode_contracts.py` | 新建 | 基于 `unittest.mock` 拦截 `httpx.AsyncClient` 的契约测试（URL / Bearer 头 / payload / 200 usage 解析 / 4xx 透传 / usage 缺失兜底） |
| 4 | `.env.example` | 改 | 顶部 Provider 列表、可选配置段、HTTP 端点覆盖段均加 opencode-go 说明 |
| 5 | `README.md` | 改 | ① Provider 表加行；② 凭证回退顺序加 opencode；③ §3 加 opencode JSON 示例；④ §5 环境变量表加 `OPENCODE_API_KEY`/`URL`/`MODEL`；⑤ §5 Provider 默认值一览加行；⑥ Kimi Code 段同步加示例 |
| 6 | `docs/Task/Active/OPENCODE_GO_PROVIDER_PLAN.md` | 新建→归档 | 本文档，完成后移到 `Archive/2026-06/` |
| 7 | `docs/Task/README.md` | 改 | 任务索引新增一行 + 完成后归档到 2026-06 |

> 不修改 `config.py` / `api_client.py` / `server.py` —— 现有 `ProviderProfile` 数据驱动已能覆盖 opencode-go（OpenAI 兼容子集）。

---

## 3. 子任务执行顺序

- [x] 3.1 编写本任务计划（PLAN.md）
- [ ] 3.2 调用 `mcp__coding-bridge__review_plan` 审查本计划（**自动触发的强制步骤**）
- [ ] 3.3 落码：`providers.py` 新增 `OPENCODE_GO` + 注册
- [ ] 3.4 落码：`tests/test_config.py` 扩 fixture + 3 个单测
- [ ] 3.5 落码：`tests/test_opencode_contracts.py` 契约 mock 测试
- [ ] 3.6 落码：`.env.example` 增加 opencode-go 相关段
- [ ] 3.7 落码：`README.md` 6 处增量更新
- [ ] 3.8 跑 `uv run pytest -q` 验证全部测试通过
- [ ] 3.9 调用 `mcp__coding-bridge__review_code` 审查代码（**自动触发的强制步骤**）
- [ ] 3.10 跑 `uv run ruff check src tests` 确认 lint 通过
- [ ] 3.11 更新 README 索引并归档本文档到 `docs/Task/Archive/2026-06/`
- [ ] 3.12 git 提交（commit 模板使用 `~/.claude/COMMIT_TEMPLATE.md`）

---

## 4. 验收标准

- `PROVIDER=opencode-go` + `API_KEY=<key>` 时，`load_settings()` 不抛异常、`validate_settings()` 通过；
- `tests/test_config.py` 新单测全部通过（含专用凭证优先于通用凭证的优先级断言）；
- `tests/test_opencode_contracts.py` 契约 mock 测试通过（URL / Authorization 头 / payload / 200 usage 解析 / 4xx 错误透传 / usage 缺失兜底）；
- `uv run pytest` 全套测试（默认配置）全绿；
- `uv run ruff check` 无新告警；
- `README.md` 增量变更无格式破损，且与代码默认值完全一致（`glm-5.2` / `96000` / `8192`）；
- 没有改动 `config.py` / `api_client.py` / `server.py`，现有 5 个 Provider 行为零变化。

### 4.1 残留风险（显式声明）

1. **认证头契约未被官方文档明确**：`Authorization: Bearer` 是按 OpenAI 兼容惯例的**推断**，文档仅描述 TUI/SDK 用法。若实际要求 `x-api-key` 或额外头（如 `OpenCode-Beta`），OpenAI 兼容子集也无法直接走现有客户端。本任务按惯例落地，README 标注需实测兜底。
2. 本次任务**不**做真实链路验证（用户未提供专用测试 API Key）。`default_max_context_chars=96000` 与 `default_max_tokens=8192` 为保守估计，README 会注明"建议生产环境按套餐规格显式覆盖"。
3. MiniMax / Qwen 走 Anthropic 协议，**首期不接**；接入需额外开发 `AnthropicApiClient`，属后续工作。

## 4.2 凭证回退顺序语义（first-match-wins）

`api_key_env_vars=["OPENCODE_API_KEY", "API_KEY"]` 表示**按顺序取第一个非空值**（语义由 `config._env` 实现）：

- 仅 `API_KEY` → 用 `API_KEY`
- 仅 `OPENCODE_API_KEY` → 用 `OPENCODE_API_KEY`
- 两者都设 → 取 `OPENCODE_API_KEY`（更靠前）

将新增一条测试锁定专用凭证优先于通用凭证的行为。

---

## 5. 风险评估与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| 认证头非 `Bearer`（推断风险） | **高** | 按惯例落地；README 显式标注"认证头为推断，需实测"；不做 live 烟测故不会误导 |
| OpenCode Go 真实 `usage` shape 与 OpenAI 标准不一致 | 中 | `_normalize_usage` 现有兜底已能处理 `prompt_tokens_details.cached_tokens` 与顶层 `cached_tokens`；若有更深差异，由 live 测试补 |
| 上下文窗口默认值 `96000` 与实际不符 | 低 | 走 `MCP_MAX_CONTEXT_CHARS` 显式覆盖；README 提示 |
| 影响其他 Provider | 极低 | 不改 `config.py` / `api_client.py`；只新增 dataclass 实例 + 字典条目 |

---

## 6. 实施参考

### 6.1 `providers.py` 新增内容（草稿）

```python
# OpenCode Go profile (OpenAI-compatible subset: GLM/Kimi/DeepSeek/MiMo).
OPENCODE_GO = ProviderProfile(
    name="opencode-go",
    mode="http",
    default_api_url="https://opencode.ai/zen/go/v1/chat/completions",
    default_model="glm-5.2",
    default_max_context_chars=96_000,
    default_max_tokens=8_192,
    api_key_env_vars=["OPENCODE_API_KEY", "API_KEY"],
    api_url_env_vars=["OPENCODE_API_URL"],
    model_env_vars=["OPENCODE_MODEL"],
)
```

并在 `PROVIDERS` 字典增加 `OPENCODE_GO.name: OPENCODE_GO,`。

### 6.2 `test_config.py` 新增内容（草稿）

```python
def test_opencode_defaults():
    os.environ["PROVIDER"] = "opencode-go"
    os.environ["OPENCODE_API_KEY"] = "oc-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "opencode-go"
    assert settings.mode == "http"
    assert settings.api_url == "https://opencode.ai/zen/go/v1/chat/completions"
    assert settings.default_model == "glm-5.2"
    assert settings.max_context_chars == 96000
    assert settings.max_tokens == 8192
    assert settings.api_password == "oc-key"


def test_opencode_uses_generic_api_key():
    os.environ["PROVIDER"] = "opencode-go"
    os.environ["API_KEY"] = "generic-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"


def test_opencode_api_key_takes_precedence_over_specific():
    os.environ["PROVIDER"] = "opencode-go"
    os.environ["API_KEY"] = "generic-key"
    os.environ["OPENCODE_API_KEY"] = "oc-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"
```

> `clean_env` fixture 需追加 `OPENCODE_API_KEY` / `OPENCODE_API_URL` / `OPENCODE_MODEL` 清理，避免污染其它测试。

### 6.3 `test_opencode_contracts.py`（草稿）

仿 `test_qianfan_contracts.py` 结构，钉死：URL = `https://opencode.ai/zen/go/v1/chat/completions`、`Authorization: Bearer <key>`、payload 含 `model=glm-5.2`、200 usage 解析、4xx 透传、usage 缺失兜底。

---

## 7. 回滚方案

本次改动为**纯增量**：新增 `ProviderProfile`、字典条目、`.env.example` 注释、README 表格行、测试用例。任一处出问题可单文件 `git revert`，不影响其他 Provider 行为。

---

## 8. 备注

- 走 `mcp__coding-bridge__review_plan` 时，PROMPT 内嵌本计划摘要，**不**让 review MCP 自行 Read 文件。
- 走 `mcp__coding-bridge__review_code` 时，PROMPT 内嵌落码后的关键 diff（`providers.py` + 新测试），**不**让 review MCP 自行 Read。

---

## 9. External Review Opinion（Plan 审查，强制步骤 3.2）

- **review_id**：`caa8b6be-5eb1-47b0-bf3c-e1322ea892eb`
- **审查结论**：有条件通过。提出 4 条意见（P0 鉴权推断 / P1 优先级 / P2 上下文 / P3 命名）。

### 主助独立判断（CLAUDE.md §4：不盲从外部审查）

| 意见 | 审查建议 | 主助判断 | 处置 |
|---|---|---|---|
| P0 鉴权推断 | 暂停、先抓包验证后编码 | 技术事实成立（确为推断）；但"暂停"与用户明确指令冲突（用户已知情推断、选择直接落地） | **不采纳暂停**；采纳 experimental 标签 + 契约测试诚实注释 |
| P1 优先级 | 改 `["OPENCODE_API_KEY","API_KEY"]` 专有优先 | 已按当前统一规则采用专用凭证优先，通用 `API_KEY` 作为兜底 | **采用 `["OPENCODE_API_KEY","API_KEY"]`** |
| P2 上下文 | 改 32000 更保守 | GLM 实际通常 128k+，32000 反而误导；qianfan 即用 96000 + 可覆盖 | **保持 96000** + README 标注需校准 |
| P3 命名 | 加 -coding 后缀统一 | opencode-go 非 Coding Plan 套餐；文档模型 ID 前缀即 `opencode-go/<model>` | **保留 opencode-go** |

### 落地调整（采纳的部分）

1. README 与 `.env.example` 对 opencode-go 标注 **experimental / 认证头为推断、需实测**；
2. `test_opencode_contracts.py` 文件 docstring 诚实声明"测试的是对 OpenAI 兼容协议的假设，非真实链路验证"；
3. 凭证回退顺序与环境变量命名维持计划原案（P1/P3 不采纳审查改法）。

---

## 10. External Review Opinion（Code 审查，强制步骤 3.9）

- **review_id**：`ff6db423-b0de-4b74-a329-2c181eea5d4e`
- **审查结论**：整体通过；提出 P0×1 / P1×3 / P2×2。

### 主助独立判断（CLAUDE.md §4：不盲从外部审查）

| # | 审查意见 | 主助判断 | 处置 |
|---|---|---|---|
| P0 | `glm-5.2` 疑似不存在，建议改 `glm-4.5` | **审查有误**：`glm-5.2` 系两次 WebFetch 从 Opencode Go 官方文档「模型 ID」列实读的精确值（全小写带连字符），`kimi-k2.7-code`/`deepseek-v4-pro` 同源。审查基于通识 GLM-4 系列，与文档实读冲突 | **不改** |
| P1.2 | URL `/zen/go/` 无据，应同等标推断 | **审查有误**：`https://opencode.ai/zen/go/v1/chat/completions` 同为文档实读；仅 Bearer 鉴权头是推断 | **不改** |
| P1.3 | 三个测试缺 `clean_env` 参数会泄漏 env | **审查有误**：`clean_env` 为 `autouse=True`，自动应用无需参数；83 passed 已证无泄漏 | **不改** |
| P1.4 | "7 tests" 与实际 10 不符 | **审查对**：系 review prompt 笔误（写 7 列 10）；实际文件 10 个测试全绿，无需改代码 | 纯描述笔误 |
| P2.5 | payload 缺 temperature 断言 | 合理但非缺陷：qianfan 契约测试同样不断言 temperature，保持基线一致 | **不改** |
| P2.6 | 缺 5xx 测试 | 合理但非缺陷：4xx/5xx 走 `HttpApiClient.call` 同一 `status_code!=200` 分支，4xx 已覆盖 | **不改** |

**结论**：所有 P0/P1 均为审查基于通识的误判或描述笔误；代码与文档实读一致，测试全绿。P2 为与 qianfan 基线对齐的合理取舍。无需修改代码。
