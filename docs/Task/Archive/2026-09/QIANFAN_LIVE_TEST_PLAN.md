# Task: Add qianfan_live end-to-end smoke test

**Status**: ✅ Completed (completion time: 2026-09-05)
**Scope**: New opt-in live smoke test for the qianfan-coding provider; mirror the existing volcengine_live / sensenova_live / deepseek_live patterns so all OpenAI-compatible Coding Plan providers share the same test surface.
**Out of scope**: New provider, contract-test changes (already covered by `test_qianfan_contracts.py`), README rewrites, CI changes.

## 1. 背景与目标

`qianfan-coding` provider 已于 2026-06-29 通过 `QIANFAN_CODING_PROVIDER_PLAN` 落地（见 Archive/2026-06），当时只新增了协议层 `test_qianfan_contracts.py`（mocked httpx），没有 live smoke test。这导致:

- 默认 `glm-5.2` 模型是否真实可服务、端点是否在线、`Bearer bce-v3/...` 鉴权是否被上游接受，都没有实测证据；
- 其他四个 OpenAI 兼容 Provider（xfyun / volcengine / opencode-go / sensenova / deepseek）都有 `-m xxx_live` 形式的 opt-in 测试，qianfan 是唯一缺位的；
- 本次刚刚用临时脚本验证了 `glm-5.3-flash` 模型可用（150 tokens，4.77s 延迟），但没有沉淀为可复用的回归测试。

目标：

1. 把临时脚本固化为 `tests/test_qianfan_live.py`，与 `test_sensenova_live.py` 同构（结构、断言、verbose 日志、redact 规则完全对齐）；
2. 在 `pyproject.toml` 注册 `qianfan_live` marker，并把 `not qianfan_live` 加进 `addopts`，与现有四个 live marker 一致；
3. 默认 pytest 套件仍然零成本（live test 在 `addopts` 里被排除），仅在显式 `pytest -m qianfan_live` 时执行。

## 2. 设计取舍

### 2.1 测试形态选择

- **复用 sensenova_live 模板**，而不是 volcengine_live 模板。理由：sensenova 是最近一次新增的 live test，结构最贴近 qianfan（OpenAI 兼容 + 单 endpoint + 无 quota-wall 分支）。
- **不引入 quota-wall 接受路径**：qianfan Coding Plan 是包月/包年 token 套餐，无明确"余额不足"语义；deepseek 的 402 / opencode-go 的 429 不适用于本 provider。
- **不调用 `server.review_code`**：与 sensenova_live 一致，直接驱动 `HttpApiClient` 而非整个 MCP pipeline —— 活体测试只验证"线缆层"（鉴权 + endpoint + 响应 schema），session 累积逻辑由 hermetic 测试覆盖。

### 2.2 模型与超时

- 使用 `settings.default_model` 作为被测模型，**不**写死 `glm-5.2` 或 `glm-5.3-flash`。这样：
  - 与 sensenova_live 模板完全对齐；
  - 测试运行者可以临时切到任意 qianfan 服务模型而无需改测试代码。
- `assert settings.default_model` 仅校验"非空"——.env 当前的 `QIANFAN_MODEL=glm-5.3-flash` 是覆盖值（profile 默认仍是 `glm-5.2`），硬编码任一具体模型名都会因为覆盖或升级而误报。漂移检测留给 README / provider profile 自身的合同测试。
- `MCP_TIMEOUT_SECONDS=120`：sensenova_live 已用此值，qianfan Coding Plan 实测 ~5s，120s 足够覆盖冷启动。
- **脱敏复用证据**：千帆与 sensenova 都走 `HttpApiClient._request_once`，对 `_request_once.py:374-377` 的 `headers` 字典统一使用 `Authorization: Bearer <key>`；`test_qianfan_contracts.test_qianfan_sends_bearer_authorization` 已经把这一假设钉死。所以 `_redact_secret`（按字符串截断 `first4****last4`，与 header 名无关）天然覆盖千帆，无需调整。
- **失败上下文**：所有 `assert` 的失败信息必须包含 `usage` 或 HTTP 状态信息（沿用 sensenova_live 的 `f"... ; usage={usage}"` 模式），便于 live test 在 CI 失败时快速定位是网络问题还是契约变更。

### 2.3 不需要新增的改动

- **provider profile**：不动 `providers.QIANFAN_CODING`（已稳定）。
- **api_client**：不动（contract 测试已经覆盖）。
- **README**：本次范围外 —— 不修改用户文档。
- **CI workflow**：项目未配置 GitHub Actions CI（无 `.github/workflows` 目录），addopts 改动足以保证默认套件不被影响。

## 3. 实施阶段

### Phase 1：测试文件

- 新增 `tests/test_qianfan_live.py`，结构与 `test_sensenova_live.py` 对称：
  - `pytestmark = pytest.mark.qianfan_live`
  - `_load_qianfan_key()`：从 `QIANFAN_API_KEY` → `API_KEY` 回退查找，无 key 时 `pytest.skip`；
  - `_redact_secret()` / `_maybe_verbose()`：与 sensenova_live 完全相同；
  - `_build_qianfan_settings(monkeypatch)`：清空旧 env，设 `PROVIDER=qianfan-coding`、`QIANFAN_API_KEY`、`MCP_TIMEOUT_SECONDS=120`，reload 模块；
  - `test_qianfan_end_to_end_smoke`：本地 config 断言 → verbose 请求打印 → 真实 POST → verbose 响应打印 → 断言 `content` 非空、含 "2"、`usage.total_tokens > 0`。

### Phase 2：marker 注册

- 修改 `pyproject.toml`：
  - 在 `markers` 列表追加 `"qianfan_live: live smoke test against the Baidu Qianfan Coding Plan API"`；
  - 在 `addopts` 末尾追加 `and not qianfan_live`。

### Phase 3：验证与归档

- 运行 `pytest -m qianfan_live tests/test_qianfan_live.py -v -s` 确认活体测试通过；
- 运行默认 `pytest` 套件确认未被污染（live tests 被 `addopts` 排除）；
- `ruff check` 通过；
- `git commit` 后归档本文档到 `docs/Task/Archive/2026-09/`，更新 `docs/Task/README.md` 索引。

## 4. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| `addopts` 漏改 `qianfan_live`，默认套件自动发真实请求 | 中：消耗真实 token 配额 | Phase 2 改完后必须跑一次默认 `pytest`，确认 live test 被跳过；CI 层面目前无工作流依赖 |
| `_load_qianfan_key` 的 env 顺序与现有 provider 不一致 | 低：测试 fail 而不是误判 | 完全照搬 sensenova_live 的实现，对照差异表（`QIANFAN_API_KEY` → `API_KEY`） |
| `settings.default_model` 漂移后断言失败 | 低：测试 fail 暴露漂移 | 仅断言 `settings.default_model` 非空；具体模型名由 provider profile / .env 决定，漂移检测留给 hermetic 测试 |
| 误用 `bce-v3/...` key 泄露到 verbose 日志 | 中：违反 secret 卫生 | `_redact_secret` 已对长度 ≥12 的 secret 做 `first4****last4` 截断（与 header 名无关）；verbose 输出仅在 `-v` 时打印；千帆使用 `Authorization: Bearer` 与 sensenova 同 schema，已由 `test_qianfan_contracts` 钉死 |

## 5. 验收标准

1. `tests/test_qianfan_live.py` 文件存在，结构与 `test_sensenova_live.py` 对称；
2. `pyproject.toml` 中 `qianfan_live` 同时出现在 `markers` 与 `addopts`（排除列表）；
3. 默认 `pytest` 不执行该测试；
4. `pytest -m qianfan_live tests/test_qianfan_live.py -v -s` 真实 POST qianfan Coding Plan 端点，返回 200 + 含 "2" 的 content + `usage.total_tokens > 0`；
5. `ruff check` 通过。

## 6. 文件变更预览

- 新增：`tests/test_qianfan_live.py`（约 220 行，与 sensenova_live 等量）
- 修改：`pyproject.toml`（markers + addopts 各加一行）
- 新增：`docs/Task/Archive/2026-09/QIANFAN_LIVE_TEST_PLAN.md`（完成后归档）
- 修改：`docs/Task/README.md`（归档后追加索引条目）

## 7. 回滚方案

变更面：1 个新增测试文件 + 1 个配置行变更。无数据库或外部状态副作用。若实施后默认 `pytest` 套件出现非预期行为：

1. `git revert <commit>` 即可完全回到原状态；
2. 若仅 live marker 注册出问题，回滚 `pyproject.toml` 的 `markers` 与 `addopts` 两行即可，测试文件可保留。
