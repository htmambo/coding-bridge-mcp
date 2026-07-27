# 指数退避重试机制实现计划

**Status**: ✅ 已完成 (完成时间: 2026-07-27)
**创建时间**: 2026-07-27
**创建人**: 果农

## 背景与问题

千帆 Token Plan 接口在请求突发时会返回系统保护错误：
```
System protection triggered by request burst. Please slow down traffic growth
and increase requests gradually before retrying.
```

当前 `HttpApiClient` 遇到任何错误直接抛出 `ApiError`，没有重试机制。当 MCP 工具被短时间内多次调用时（如 code review 场景的连续调用），容易触发限流导致调用失败。

## 目标

在 `HttpApiClient.call` 中实现指数退避重试机制，对可重试错误（限流、超时、5xx）自动重试，降低因流量波动导致的失败率。

## 变更范围

### 1. `src/coding_bridge_mcp/api_client.py`
- 新增 `_is_retryable_error()` 函数，判断错误是否可重试
- 新增 `_get_retry_after()` 函数，从响应头中提取 `Retry-After`
- 新增 `max_retries` / `retry_base_delay` 配置（从 Settings 读取）
- 在 `HttpApiClient.call` 中包裹重试循环（指数退避 + 抖动）

### 2. `src/coding_bridge_mcp/config.py`
- `Settings` 新增 `max_retries: int = 3` 和 `retry_base_delay: float = 1.0`
- 新增 `MCP_MAX_RETRIES` / `MCP_RETRY_BASE_DELAY` 环境变量解析
- `validate_settings` 增加对应校验

### 3. 测试文件
- 新增 `tests/test_api_client_retry.py` 覆盖：
  - 429 重试（含 Retry-After 头）
  - 5xx 重试
  - 超时重试
  - 不可重试错误（4xx 非限流）不重试
  - 重试次数耗尽后抛 ApiError
  - 指数退避时间递增
  - 成功后立即返回（不继续重试）

## 重试策略设计

### 可重试错误类型
| 错误类型 | 判定条件 |
|---|---|
| HTTP 429 | `status_code == 429` |
| HTTP 5xx | `status_code >= 500` |
| 限流关键词 | 4xx 响应体包含 `burst` / `rate limit` / `quota` / `too many requests` / `系统保护` 等 |
| 超时 | `httpx.TimeoutException` |
| 连接错误 | `httpx.RequestError`（连接失败、DNS 错误等网络抖动） |

### 退避算法
- 基础延迟：`base_delay`（默认 1s）
- 第 n 次重试延迟：`base_delay * 2^(n-1)`，上限 30s
- 增加 ±20% 随机抖动，避免惊群效应
- 若响应头有 `Retry-After`，优先使用其值（取最大值，确保不早于服务端要求）

### 重试次数
- 默认 `max_retries = 3`（即最多发 4 次请求：1 次初始 + 3 次重试）
- 可通过 `MCP_MAX_RETRIES=0` 关闭重试

## 日志

- 每次重试前输出 `warn` 级日志：`http_retry`（包含重试次数、延迟、错误原因）
- 最终失败输出 `error` 级日志：`http_final_failure`

## 验收标准

1. ✅ 单元测试全部通过（`pytest tests/test_api_client_retry.py`）
2. ✅ 现有测试不受影响（`pytest` 全量通过）
3. ✅ 默认配置下行为向后兼容（只是失败率降低）
4. ✅ 可通过环境变量关闭重试（`MCP_MAX_RETRIES=0`）

## 风险与缓解

| 风险 | 缓解措施 |
|---|---|
| 重试增加延迟 | 默认仅 3 次，最大延迟约 8s，总延迟可控 |
| 非幂等请求重复提交 | chat/completions 是幂等的，无副作用 |
| 日志量增加 | 重试日志为 warn 级，正常情况不触发 |
