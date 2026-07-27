# Task: MCP 性能与运行稳定性优化

**Status**: Proposed
**Scope**: HTTP 连接复用、会话并发、内存边界、输入大小、错误处理与性能观测。
**Out of scope**: Provider 协议改造、默认 Provider 切换、持久化会话、强制启用重试或流式响应。

## 1. 背景与目标

当前服务的主要本地开销不在 Python 计算，而在以下路径：

- `HttpApiClient.call()` 每次请求都创建并关闭 `httpx.AsyncClient`，无法复用连接；
- 同一 `SESSION_ID` 的并发调用没有按会话串行化，可能发送错误或膨胀的上下文；
- `_sessions` 和 `_session_stats` 没有 TTL 或容量上限，长时间运行会持续增长；
- 单条超大消息可以绕过 `MCP_MAX_CONTEXT_CHARS`；
- 请求耗时、重试、连接池和错误响应大小缺少可观测与边界控制。

目标：

1. 降低重复 DNS/TCP/TLS 建连带来的延迟，控制并发连接数；
2. 保证同一会话的消息顺序和上下文一致，不牺牲不同会话之间的并发；
3. 让长时间运行的 stdio MCP 进程具有可预测的内存上限；
4. 在请求发出前阻止超出本地预算的输入；
5. 能通过日志区分本地排队、连接、上游响应和模型生成造成的耗时。

## 2. 设计取舍

### 2.1 HTTP 客户端生命周期

- `HttpApiClient` 持有单个异步 `httpx.AsyncClient`，同一进程内复用 keep-alive 连接；
- 通过 FastMCP lifespan 或等价的进程退出钩子调用 `aclose()`；
- 保留现有 `PROXY` 语义，代理设置只在客户端初始化时解析一次；
- 增加显式连接池上限，避免并发工具调用耗尽文件描述符；
- 将单一超时拆为 connect/read/write/pool 四类，保留 `MCP_TIMEOUT_SECONDS` 作为兼容的 read 总上限。

### 2.2 会话并发与数据结构

- 为每个 session 分配独立 `asyncio.Lock`，同一 session 的完整 turn 串行执行；
- 不使用全局锁包住网络请求，不同 session 仍可并发访问上游；
- 会话数据与统计数据一起淘汰，避免只清理消息而遗留统计；
- 默认采用 TTL + 最大会话数的双重边界，淘汰策略使用 LRU 或按最后访问时间；
- 保持现有 `SESSION_ID` 行为和返回字段兼容，淘汰后的会话按未知会话处理。

### 2.3 输入与上下文预算

- 在写入 session 前校验单条 user 内容的最大字符数，超限返回可操作的错误；
- 保留 system prompt，优先保留最近的完整 user/assistant turn；
- 第一阶段继续使用字符预算，避免引入供应商绑定的 tokenizer；
- 将字符预算、消息数和单条消息预算分别配置，后续根据真实 token 指标再评估 token-aware 裁剪；
- `return_all_messages=true` 继续支持调试，但对返回历史设置独立上限，避免响应本身过大。

### 2.4 重试、流式与缓存

- 本次不默认启用自动重试。先记录 429/5xx/网络错误及延迟，确认供应商行为和费用风险；
- 后续如启用重试，只覆盖明确的瞬态错误，尊重 `Retry-After`，限制次数并允许关闭；
- 流式响应作为独立设计，不在本次改动中改变现有 Dict 返回契约；
- 不在通用客户端中假设 Provider 支持上下文缓存，先使用 usage 指标验证收益。

## 3. 实施阶段

### Phase 1：连接复用与会话正确性

修改范围：`src/coding_bridge_mcp/api_client.py`、`src/coding_bridge_mcp/server.py`。

工作项：

1. 为 `HttpApiClient` 增加异步客户端初始化、复用和关闭路径；
2. 增加连接池 limits 和分项 timeout 配置，保持现有代理测试语义；
3. 为 session 增加独立锁，并将“追加 user → API 调用 → 追加 assistant”作为一个串行 turn；
4. 保持 API 错误时的会话语义明确：记录 user 输入，但不追加 assistant；
5. 增加请求耗时日志字段 `elapsed_ms`，至少覆盖成功、HTTP 错误和网络异常。

验收：

- 连续两次调用复用同一 `AsyncClient`；
- 同一 session 的并发测试按调用顺序得到稳定消息历史；
- 不同 session 能并发执行；
- 客户端关闭后不会留下未关闭连接或异步任务；
- 现有代理、Provider contract 和工具 E2E 测试全部通过。

### Phase 2：内存和输入边界

修改范围：`src/coding_bridge_mcp/config.py`、`src/coding_bridge_mcp/server.py`、`.env.example`、`docs/CONFIGURATION.md`。

工作项：

1. 增加 session TTL、最大 session 数、单条消息最大字符数和调试历史最大字符数配置；
2. 对配置值做正数、有限值和合理上限校验；
3. 实现惰性清理或定期清理，避免每次请求都扫描全部 session；
4. 修正单条超大消息绕过上下文预算的问题；
5. 将 `_sessions` 和 `_session_stats` 的淘汰保持原子一致；
6. 对错误响应 body 和 `return_all_messages` 做长度截断。

验收：

- 超限输入不会发出上游请求；
- 超过 TTL 或容量的 session 可预测地淘汰；
- token 统计不会保留已淘汰 session；
- 压力测试下进程内存不随一次性 session 数线性无限增长；
- 配置文档、`.env.example` 和测试覆盖新增变量。

### Phase 3：观测和策略评估

修改范围：`src/coding_bridge_mcp/api_client.py`、`src/coding_bridge_mcp/logging_config.py`、测试和文档。

工作项：

1. 记录请求阶段耗时、状态码、响应大小、连接复用相关信息和上下文大小；
2. 增加可选的并发上限和排队耗时指标；
3. 用真实或录制的 429/502/503 响应评估是否需要选择性重试；
4. 单独评估流式 MCP 返回契约，不与本次连接复用改动绑定；
5. 根据 usage 和延迟数据决定是否需要 token-aware 裁剪或 Provider 级缓存。

验收：

- 日志可定位慢在本地排队、连接建立还是上游响应；
- 统计字段不会包含 API Key、代理密码或完整响应 body；
- 重试策略若实现，具有最大次数、退避和关闭开关；
- 未实现的流式/缓存能力不改变当前默认行为。

## 4. 测试计划

新增或扩展以下测试：

- `test_api_client.py`：客户端复用、关闭、连接池、分项超时、错误 body 截断；
- `test_session.py`：同 session 并发顺序、不同 session 并发、单条超限输入、TTL/LRU 淘汰；
- `test_tools_e2e.py`：淘汰后的 session、`return_all_messages` 上限、API 错误后的历史一致性；
- 性能 smoke test：固定响应下比较首次请求与后续请求的客户端创建次数和耗时；
- 全量门禁：`uv lock --locked`、`uv run ruff check .`、`uv run pytest -q`。

## 5. 发布与回滚

- 每个 Phase 独立提交，先发布 Phase 1，再观察连接错误率、平均/ p95 延迟和进程内存；
- 新配置全部提供兼容默认值，未设置时不改变现有用户行为；
- 若持久连接导致特定 Provider 或代理异常，可通过配置关闭 keep-alive 或回退为每请求客户端；
- 若 session 淘汰影响长会话，优先调大 TTL/容量，不恢复无限增长；
- 重试、流式和 token-aware 裁剪必须单独发布，避免与基础稳定性改动混合。

## 6. 外部审查

计划形成后应调用 `mcp__coding-bridge__review_plan`，保存返回的 `SESSION_ID`，并在每个 Phase 完成代码修改后调用 `mcp__coding-bridge__review_code`。当前审查环境未暴露这些工具时，以本地测试、性能指标和人工复核作为替代，并在提交说明中记录。
