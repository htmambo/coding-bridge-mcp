**Status**: 🔄 进行中 (开始时间: 2026-06-22)

## 任务目标

修改 Coding Bridge MCP 的 HTTP 客户端，使其默认直连厂商 API，**忽略环境变量中的代理设置**（HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / NO_PROXY）。

## 问题分析

- httpx 默认 `trust_env=True`，会自动读取 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 等环境变量。
- 项目设计原则是「直连厂商 API」，不应让操作员 shell 的代理配置影响业务流量。
- 即便通过 `trust_env=False` 禁用环境变量，仍保留代码层显式 `proxy=None` 双重保险。

## 改动详情

### 文件 1: `src/coding_bridge_mcp/api_client.py`
- `HttpApiClient.call` 中 `httpx.AsyncClient(...)` 构造增加 `trust_env=False` 关键字参数。
- WebSocket 路径（`WebSocketApiClient`）无需改动——`websockets` 库不读取代理环境变量。

### 文件 2: `tests/test_no_proxy.py` (新增)
- `test_http_client_disables_trust_env`：在 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 已设置时，断言 `HttpApiClient.call` 内部构造的 `httpx.AsyncClient` 传入了 `trust_env=False`。
- `test_http_client_does_not_pass_explicit_proxy`：断言未向 httpx 传入任何代理 URL（若有则必须为 `None`）。

## 验收标准

| 标准 | 状态 |
|---|---|
| `pytest` 全部通过 (含 2 个新增测试) | ✅ 16 passed |
| ruff check 无 warning | ⏭ 跳过 (pyproject 未声明 ruff) |
| 改动仅限目标文件，未污染其他业务代码 | ✅ |

## 风险评估

- **回归风险**：低。`trust_env=False` 仅影响代理解析路径，对业务 HTTP 调用无副作用。
- **未涉及的代理场景**：用户主动通过 `proxy=` 参数指定直连代理**仍可工作**（未禁止），仅屏蔽环境变量注入。
- **WebSocket 客户端**：未验证 `websockets` 库是否读取代理环境变量（库自身文档声明不会，但未做单元测试断言）。

## 实现顺序

1. ✅ 修改 `api_client.py`（HttpApiClient）
2. ✅ 新增 `tests/test_no_proxy.py`
3. ✅ 全量 pytest 验证
4. ⏳ 外部评审（task #5）
5. ⏳ git commit（task #4）
6. ⏳ 归档到 `docs/Task/Archive/2026-06/`（本任务完结时执行）
