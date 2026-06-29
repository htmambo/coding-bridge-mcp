# Task: 新增 百度千帆 Coding Plan Provider（`qianfan-coding`）

**Status**: 🔄 In progress (start time: 2026-06-29)
**Author**: Claude
**Scope**: 新增一个 Provider，不影响其他 Provider 的现有行为。

---

## 1. 背景与目标

### 背景

`coding-bridge-mcp` 当前已支持 4 个 Provider：

- `xfyun-coding`（讯飞星辰 MaaS Coding Plan，默认）
- `xfyun-http`（讯飞星火通用 OpenAI 兼容）
- `xfyun-websocket`（讯飞星火原生 WebSocket）
- `volcengine-coding`（火山方舟 Coding Plan 个人版）

用户希望接入**百度智能云千帆 Coding Plan** 作为第 5 个 Provider。

### 目标

1. 新增 `qianfan-coding` Provider，遵循现有 `ProviderProfile` 数据驱动模式；
2. 复用 `HttpApiClient`（千帆 Coding Plan 走 OpenAI 兼容端点），**不新增协议层代码**；
3. 沿用通用 `API_KEY` 入口，凭证体验与现有 Provider 保持一致；
4. 更新文档、`.env.example`、测试与 README 表。

### 关键设计决策

| 决策点 | 结论 | 依据 |
|---|---|---|
| 接入协议 | **OpenAI 兼容**（HTTP Bearer） | 用户已确认走 `https://qianfan.baidubce.com/v2/coding` |
| 客户端实现 | **复用 `HttpApiClient`** | OpenAI 兼容 + 现有 `usage` 解析已覆盖 |
| Provider 名 | `qianfan-coding` | 与 `volcengine-coding` 风格对齐 |
| 默认端点 | `https://qianfan.baidubce.com/v2/coding` | 用户指定 |
| 默认模型 | `qianfan-code-latest` | 用户指定 |
| 凭证入口 | `API_KEY` → `QIANFAN_API_KEY` 回退 | 与 `volcengine-coding` 体验一致 |
| 端点覆盖变量 | `QIANFAN_API_URL` | 与 `VOLCENGINE_API_URL` 对齐 |
| 模型覆盖变量 | `QIANFAN_MODEL` | 与 `VOLCENGINE_MODEL` 对齐 |
| 上下文窗口默认值 | `96000` | 与 `xfyun-coding` 同档（千帆 Coding Plan 套餐规格未在用户侧提供，先取保守中间值；README 会注明可由 `MCP_MAX_CONTEXT_CHARS` 覆盖） |
| 单次输出 token 默认 | `8192` | 与 `xfyun-coding` / `volcengine-coding` 一致 |

> **重要边界**：本次任务不创建 live 烟测脚本（`test_qianfan_live.py`）。
> 原因：用户仅提供了端点 URL 与默认模型名，未提供专用测试 API Key。参考
> `test_volcengine_live.py` 的 opt-in 模式，留待后续有 key 时再补。

---

## 2. 改动清单

| # | 文件 | 变更类型 | 概要 |
|---|---|---|---|
| 1 | `src/coding_bridge_mcp/providers.py` | 改 | 新增 `QIANFAN_CODING` Profile + 注册到 `PROVIDERS` |
| 2 | `tests/test_config.py` | 改 | 新增 `test_qianfan_defaults` 与 `test_qianfan_uses_generic_api_key` |
| 3 | `.env.example` | 改 | 顶部 Provider 列表、可选配置段、HTTP 端点覆盖段均加千帆说明 |
| 4 | `README.md` | 改 | ① Provider 表加行；② 环境变量表加 `QIANFAN_API_KEY`/`QIANFAN_API_URL`/`QIANFAN_MODEL`；③ §3「配置 API Key」加千帆 JSON 示例；④ §5「Provider 默认值一览」加行；⑤ Kimi Code 段同步加示例 |
| 5 | `AGENTS.md` | 改 | 在尾部「扩展 Provider」段加千帆说明（可选；视情况） |
| 6 | `docs/Task/Active/QIANFAN_CODING_PROVIDER_PLAN.md` | 新建→归档 | 本文档，完成后移到 `Archive/2026-06/` |
| 7 | `docs/Task/README.md` | 改 | 任务索引新增一行 + 完成后归档到 2026-06 |

> 不修改 `config.py` / `api_client.py` / `server.py` —— 现有 `ProviderProfile` 数据驱动已能覆盖千帆。

---

## 3. 子任务执行顺序

- [x] 3.1 编写本任务计划（PLAN.md）
- [x] 3.2 调用 `mcp__coding-bridge__review_plan` 审查本计划（**自动触发的强制步骤**）—— review_id=8e64d66d-…
- [ ] 3.3 落码：`providers.py` 新增 `QIANFAN_CODING` + 注册
- [ ] 3.4 落码：`tests/test_config.py` 新增 Provider 默认值 + 凭证回退顺序两个单测
- [ ] 3.5 落码：`tests/test_proxy_modes.py`（或新文件）新增基于 `patch(httpx.AsyncClient, ...)` 的契约 mock 测试，断言：
  - URL = `https://qianfan.baidubce.com/v2/coding`
  - `Authorization: Bearer <key>`
  - payload 含 `model=qianfan-code-latest` 与 `messages`
  - 200 响应下 `usage` 走 `_normalize_usage` 正确解析
  - 4xx 响应错误信息透传
- [ ] 3.6 落码：`.env.example` 增加千帆相关段
- [ ] 3.7 落码：`README.md` 5 处增量更新（Provider 表 / 环境变量表 / §3 千帆 JSON 示例 / §5 Provider 默认值一览 / Kimi Code 段示例）
- [ ] 3.8 跑 `uv run pytest -q` 验证全部测试通过
- [ ] 3.9 调用 `mcp__coding-bridge__review_code` 审查代码（**自动触发的强制步骤**）
- [ ] 3.10 跑 `uv run ruff check src tests` 确认 lint 通过
- [ ] 3.11 更新 README 索引并归档本文档到 `docs/Task/Archive/2026-06/`
- [ ] 3.12 git 提交（commit 模板使用 `~/.claude/COMMIT_TEMPLATE.md`）

---

## 4. 验收标准

- `PROVIDER=qianfan-coding` + `API_KEY=<key>` 时，`load_settings()` 不抛异常、`validate_settings()` 通过；
- `tests/test_config.py` 中新单测全部通过（含「同时设置 `API_KEY` 与 `QIANFAN_API_KEY` 时取前者」的优先级断言，见下文 §6.1）；
- `tests/test_proxy_modes.py` 中新增的契约 mock 测试通过（URL / Authorization 头 / payload / 200 usage 解析 / 4xx 错误透传）；
- `uv run pytest` 全套测试（默认配置）全绿；
- `uv run ruff check` 无新告警；
- `README.md` 5 处增量变更无格式破损，且与代码默认值完全一致（`qianfan-code-latest` / `96000` / `8192`）；
- 没有改动 `config.py` / `api_client.py` / `server.py`，现有 4 个 Provider 行为零变化。

### 4.1 残留风险（显式声明）

本次任务**不**做真实链路验证（用户未提供专用测试 API Key）。`default_max_context_chars=96000` 与 `default_max_tokens=8192` 为保守估计，README 中会注明"建议生产环境按套餐规格显式覆盖"。

## 4.2 凭证回退顺序语义（first-match-wins）

`api_key_env_vars=["API_KEY", "QIANFAN_API_KEY"]` 表示**按顺序取第一个非空值**（与 `volcengine-coding` 的 `["API_KEY", "VOLCENGINE_API_KEY", "ARK_API_KEY"]` 一致；语义由 `config._env` 实现）。即：

- 仅 `API_KEY` → 用 `API_KEY`
- 仅 `QIANFAN_API_KEY` → 用 `QIANFAN_API_KEY`
- 两者都设 → 取 `API_KEY`（更靠前）

将新增一条测试 `test_qianfan_api_key_takes_precedence_over_specific` 锁定该行为。

---

## 5. 风险评估与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| 千帆 Coding Plan 真实 `usage` shape 与 OpenAI 标准不完全一致 | 中 | `_normalize_usage` 现有兜底已能处理 `prompt_tokens_details.cached_tokens` 与顶层 `cached_tokens`；若有更深差异，由 live 测试补 |
| 千帆鉴权头非 `Bearer`（如需 `apiKey` 头字段） | 中 | 用户已声明走 OpenAI 兼容；本任务范围内**假设** Bearer。若实际不通过，需追加 `Authorization` 之外的 header（属后续工作） |
| 上下文窗口默认值 `96000` 与实际套餐不符 | 低 | 走 `MCP_MAX_CONTEXT_CHARS` 显式覆盖；README 提示 |
| 影响其他 Provider | 极低 | 不改 `config.py` / `api_client.py`；只新增 dataclass 实例 + 字典条目 |

---

## 6. 实施参考

### 6.1 `providers.py` 新增内容（草稿）

```python
# Baidu Qianfan Coding Plan profile
QIANFAN_CODING = ProviderProfile(
    name="qianfan-coding",
    mode="http",
    default_api_url="https://qianfan.baidubce.com/v2/coding",
    default_model="qianfan-code-latest",
    default_max_context_chars=96_000,
    default_max_tokens=8_192,
    api_key_env_vars=["API_KEY", "QIANFAN_API_KEY"],
    api_url_env_vars=["QIANFAN_API_URL"],
    model_env_vars=["QIANFAN_MODEL"],
)
```

并在 `PROVIDERS` 字典增加 `QIANFAN_CODING.name: QIANFAN_CODING,`。

### 6.2 `test_config.py` 新增内容（草稿）

```python
def test_qianfan_defaults():
    os.environ["PROVIDER"] = "qianfan-coding"
    os.environ["QIANFAN_API_KEY"] = "qianfan-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.provider == "qianfan-coding"
    assert settings.mode == "http"
    assert settings.api_url == "https://qianfan.baidubce.com/v2/coding"
    assert settings.default_model == "qianfan-code-latest"
    assert settings.api_password == "qianfan-key"


def test_qianfan_uses_generic_api_key():
    os.environ["PROVIDER"] = "qianfan-coding"
    os.environ["API_KEY"] = "generic-key"
    reload(config_module)
    settings = config_module.load_settings()
    config_module.validate_settings(settings)

    assert settings.api_password == "generic-key"
```

> `clean_env` fixture 已有 `monkeypatch.delenv` 列表，**新加的 `QIANFAN_*` / `QIANFAN_API_KEY` / `QIANFAN_API_URL` / `QIANFAN_MODEL` 需在 fixture 中也清理**，避免污染其它测试。

---

## 7. 回滚方案

本次改动为**纯增量**：新增 `ProviderProfile`、字典条目、`.env.example` 注释、README 表格行、测试用例。任一处出问题可单文件 `git revert`，不影响其他 Provider 行为。

---

## 8. 备注

- 走 `mcp__coding-bridge__review_plan` 时，PROMPT 内嵌本计划摘要，**不**让 review MCP 自行 Read 文件。
- 走 `mcp__coding-bridge__review_code` 时，PROMPT 内嵌落码后的关键 diff（`providers.py` + `test_config.py`），**不**让 review MCP 自行 Read。
