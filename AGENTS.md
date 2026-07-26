# Coding Bridge MCP 自动审查规范

本项目已接入 `coding-bridge` MCP Server（火山方舟 / 讯飞 Coding Plan）。你必须在以下节点主动调用对应的 MCP 工具，并把审查结论纳入最终回复。

## 1. 计划审查（形成思路后）

在形成初步实现思路、但尚未开始编码前，调用：

- `mcp__coding-bridge__review_plan`
- 参数：
  - `PLAN`：当前实现计划或方案文本
  - `cd`：当前项目根目录
  - `CONTEXT`：项目背景、约束、目标（可选但推荐）
  - `SESSION_ID`：空字符串开始新会话；如需追问则沿用返回的 ID
  - `model`：模型版本（可选，留空用 provider 默认模型）
  - `return_all_messages`：返回完整消息历史（可选，默认 false，调试用）

## 2. 代码审查（完成修改后）

**每次对 `src/`、`tests/` 或配置文件做出实质性修改后，必须调用：**

- `mcp__coding-bridge__review_code`
- 参数：
  - `CODE`：需要审查的完整代码或 diff。优先传入完整相关函数/类，确保上下文完整。
  - `cd`：当前项目根目录
  - `REQUIREMENTS`：额外上下文，例如修改原因、边界情况、需要重点关注的点
  - `SESSION_ID`：空字符串开始新会话；如需追问则沿用返回的 ID
  - `model`：模型版本（可选，留空用 provider 默认模型）
  - `return_all_messages`：返回完整消息历史（可选，默认 false，调试用）

## 3. 多轮追问（保存 SESSION_ID）

每次调用 `review_plan` / `review_code` / `chat` 后，返回中都会包含 `SESSION_ID`。**必须保存该 ID**，以便对同一话题继续追问，保持上下文连续。

## 4. 判断原则

Coding Plan / 星火返回的审查结论**仅供参考**。你仍需保持独立判断，不盲从；对于明显不合理的建议，应在最终回复中说明原因。

## 5. 何时必须审查

- 新增功能、修复 bug、重构代码之后
- 修改核心配置（如 `pyproject.toml`、Provider 默认值、API 客户端）之后
- 在最终向用户汇报“已完成”之前，确认已执行 review

## 6. 工具列表速查

- `mcp__coding-bridge__chat` — 通用多轮对话
- `mcp__coding-bridge__review_code` — 代码审查
- `mcp__coding-bridge__review_plan` — 计划/方案审查
- `mcp__coding-bridge__get_token_stats` — 查询当前累计 token 用量
