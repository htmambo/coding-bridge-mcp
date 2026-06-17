# Astron MCP

基于 [MCP 协议](https://modelcontextprotocol.io) 封装的**讯飞星火 / 讯飞星辰 Coding Plan** 服务，为 Claude Code 等 AI 编程工具提供代码审查、计划审查与多轮对话能力。

本项目参考了 [KimiMCP](https://github.com/htmambo/kimimcp) 的工具签名与返回结构，但在底层直接调用讯飞 API（无官方 CLI），并针对**不同订阅类型**做了适配。

---

## 一、支持的订阅类型

| 模式 | `SPARK_MODE` | 凭证 | 默认端点 | 说明 |
|------|--------------|------|----------|------|
| **Coding Plan** | `coding` | `SPARK_API_PASSWORD`（套餐订阅页面的 API Key） | `https://maas-coding-api.cn-huabei-1.xf-yun.com/v2/chat/completions` | 面向 Claude Code / Cursor / OpenClaw 等编程工具，按请求次数计费 |
| 星火 OpenAI 兼容 | `http` | `SPARK_API_PASSWORD`（APIPassword） | `https://spark-api-open.xf-yun.com/v1/chat/completions` | 通用星火大模型按 token 计费 |
| 星火原生 WebSocket | `websocket` | `SPARK_APP_ID` + `SPARK_API_KEY` + `SPARK_API_SECRET` | `wss://spark-api.xf-yun.com/v4.0/chat` | 原生协议，需签名 |

> **注意**：Coding Plan 的 API Key 仅限在编程工具交互场景中使用，禁止用于自动化脚本、批量任务或自建后端。

---

## 二、快速开始

### 1. 安装 uv（如果还没有）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 克隆并进入项目

```bash
git clone https://github.com/htmambo/astronmcp.git
cd astronmcp
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

> 提示：Astron MCP 启动时会自动加载当前工作目录下的 `.env` 文件（不覆盖已有的环境变量），所以本地使用时不必手动 `source`。

Coding Plan 用户最少只需要：

```env
SPARK_MODE=coding
SPARK_API_PASSWORD=your-coding-plan-api-key
```

### 4. 安装依赖

```bash
uv sync
```

### 5. 接入 Claude Code

**方式 A：本地开发（推荐，方便改配置和二次开发）**

```bash
claude mcp add astron -s user --transport stdio -- uv run --python 3.12 astronmcp
```

**方式 B：直接从 GitHub 安装（无需克隆）**

```bash
claude mcp add astron -s user --transport stdio -- uvx --from git+https://github.com/htmambo/astronmcp.git astronmcp
```

> 注意：方式 B 需要你在 Claude Code 配置中注入环境变量（见下文「配置 API Key」），或者从已设置好环境变量的 Shell 启动 Claude Code。

验证：

```bash
claude mcp list
```

应看到 `astron: uv run --python 3.12 astronmcp - ✓ Connected` 或 `astron: uvx --from git+https://github.com/htmambo/astronmcp.git astronmcp - ✓ Connected`。

---

## 三、配置 API Key

MCP Server 作为 Claude Code 的子进程运行，需要从环境变量读取密钥。`claude mcp add` 不能直接带 `--env`，推荐通过 `~/.claude/settings.json` 注入：

```json
{
  "mcpServers": {
    "astron": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/htmambo/astronmcp.git",
        "astronmcp"
      ],
      "env": {
        "SPARK_MODE": "coding",
        "SPARK_API_PASSWORD": "your-coding-plan-api-key"
      }
    }
  }
}
```

如果你用的是本地克隆的方式 A，配置长这样：

```json
{
  "mcpServers": {
    "astron": {
      "command": "uv",
      "args": ["run", "--python", "3.12", "astronmcp"],
      "env": {
        "SPARK_MODE": "coding",
        "SPARK_API_PASSWORD": "your-coding-plan-api-key"
      }
    }
  }
}
```

> 修改配置后，重启 Claude Code 或运行 `claude mcp list` 刷新。

### 替代方案：从 Shell 启动

如果你用的是 Claude Code CLI，也可以在启动它的 Shell 中导出环境变量：

```bash
export SPARK_MODE=coding
export SPARK_API_PASSWORD=your-coding-plan-api-key
claude
```

但这种方式对桌面版 Claude 无效，建议优先使用 `settings.json`。

---

## 四、工具说明

### `spark` — 通用多轮对话

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `PROMPT` | `str` | ✅ | 任务指令 |
| `cd` | `Path` | ✅ | 工作目录 |
| `SESSION_ID` | `str` | ❌ | 继续会话，空则新建 |
| `model` | `str` | ❌ | 模型版本，默认 `SPARK_DEFAULT_MODEL` |
| `return_all_messages` | `bool` | ❌ | 是否返回完整历史 |

返回值：

```json
{
  "success": true,
  "SESSION_ID": "uuid-string",
  "agent_messages": "模型回复内容...",
  "usage": { "prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300 }
}
```

### `spark_review_code` — 代码审查

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `CODE` | `str` | ✅ | 要审查的代码 |
| `cd` | `Path` | ✅ | 工作目录 |
| `REQUIREMENTS` | `str` | ❌ | 额外要求/上下文 |
| `SESSION_ID` | `str` | ❌ | 继续会话 |
| `model` | `str` | ❌ | 模型版本 |
| `return_all_messages` | `bool` | ❌ | 返回完整历史 |

### `spark_review_plan` — 计划/方案审查

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `PLAN` | `str` | ✅ | 计划文本 |
| `cd` | `Path` | ✅ | 工作目录 |
| `CONTEXT` | `str` | ❌ | 项目背景 |
| `SESSION_ID` | `str` | ❌ | 继续会话 |
| `model` | `str` | ❌ | 模型版本 |
| `return_all_messages` | `bool` | ❌ | 返回完整历史 |

---

## 五、环境变量完整列表

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SPARK_MODE` | `coding` | `coding` / `http` / `websocket` |
| `SPARK_API_PASSWORD` | - | Coding Plan / HTTP 模式的 API Key 或 APIPassword |
| `SPARK_API_KEY` | - | `SPARK_API_PASSWORD` 的别名 |
| `SPARK_APP_ID` | - | WebSocket 模式 AppID |
| `SPARK_API_KEY` | - | WebSocket 模式 APIKey |
| `SPARK_API_SECRET` | - | WebSocket 模式 APISecret |
| `SPARK_API_URL` | 见模式 | 完整 HTTP 端点 |
| `SPARK_WS_URL` | `wss://spark-api.xf-yun.com/v4.0/chat` | WebSocket 端点 |
| `SPARK_DEFAULT_MODEL` | `astron-code-latest` | 默认模型 ID |
| `SPARK_TIMEOUT_SECONDS` | `120` | 请求超时 |
| `SPARK_MAX_CONTEXT_CHARS` | `96000` | 上下文字符上限（粗略） |
| `SPARK_MAX_MESSAGES` | `40` | 单会话最大消息数 |
| `SPARK_MAX_TOKENS` | `8192` | 单次最大输出 tokens |

---

## 六、在 Claude Code 提示词中推荐使用

在 `~/.claude/CLAUDE.md` 中加入类似内容，可让 Claude Code 在编码流程中主动调用审查工具：

```markdown
## Astron MCP 使用规范

1. 在形成初步实现思路后，可调用 `spark_review_plan` 审查实施计划。
2. 完成代码修改后，必须调用 `spark_review_code` 审查改动。
3. 保存每次返回的 `SESSION_ID`，以便对同一话题进行多轮追问。
4. 星火/Coding Plan 的回复仅供参考，你仍需保持独立判断。
```

---

## 七、常见问题

**Q: Coding Plan 返回 401 怎么办？**

- 确认 API Key 来自「套餐订阅」页面，而不是星火大模型控制台。
- 确认 `SPARK_MODE=coding`。
- 确认 model 使用 `astron-code-latest`（默认）。

**Q: 模型底层怎么切换？**

在 [讯飞星辰 MaaS 套餐订阅页面](https://maas.xfyun.cn/packageSubscription) 点击「配置模型」，1-3 分钟后生效。API 层仍使用 `astron-code-latest`。

**Q: 出现 429 / 请求速率限制？**

Coding Plan 有 5 小时/周/月的请求次数限制，高峰期也可能触发平台限流。代码已透传错误信息，建议稍后重试或升级套餐。

---

## 八、许可证

MIT
