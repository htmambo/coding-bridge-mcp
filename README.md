# Coding Bridge MCP

基于 [MCP 协议](https://modelcontextprotocol.io) 封装的多厂商 **Coding Plan** 服务，目前已支持讯飞星火 / 讯飞星辰 Coding Plan 与火山方舟 Coding Plan 个人版，为 Claude Code 等 AI 编程工具提供代码审查、计划审查与多轮对话能力。

本项目参考了 [KimiMCP](https://github.com/htmambo/kimimcp) 的工具签名与返回结构，但在底层直接调用讯飞 API（无官方 CLI），并针对**不同订阅类型**做了适配。

---

## 一、支持的 Provider

Coding Bridge MCP 通过统一的 OpenAI 兼容 HTTP 客户端接入多个厂商的 Coding Plan / 大模型服务。

| Provider | 协议 | 凭证 | 默认端点 | 默认模型 |
|----------|------|------|----------|----------|
| **xfyun-coding**（默认） | OpenAI 兼容 | `API_KEY`（HTTP Bearer） | `https://maas-coding-api.cn-huabei-1.xf-yun.com/v2/chat/completions` | `astron-code-latest` |
| **xfyun-http** | OpenAI 兼容 | `API_KEY`（HTTP Bearer） | `https://spark-api-open.xf-yun.com/v1/chat/completions` | `4.0Ultra` |
| **xfyun-websocket** | 原生 WebSocket | `SPARK_APP_ID` + `SPARK_API_KEY`（签名）+ `SPARK_API_SECRET` | `wss://spark-api.xf-yun.com/v4.0/chat` | `4.0Ultra` |
| **volcengine-coding** | OpenAI 兼容 | `API_KEY`（HTTP Bearer） | `https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions` | `ark-code-latest` |

> **注意**：Coding Plan 类套餐（讯飞、火山）的 API Key **仅限在 AI 编程工具交互场景中使用**，禁止用于自动化脚本、批量任务或自建后端。

切换 Provider 只需修改 `PROVIDER` 环境变量（旧版 `SPARK_MODE` 仍兼容）。为统一凭证入口，推荐使用通用变量 `API_KEY`：

```env
# 讯飞 Coding Plan
PROVIDER=xfyun-coding
API_KEY=your-xfyun-key

# 火山方舟 Coding Plan 个人版
PROVIDER=volcengine-coding
API_KEY=your-volcano-key

# 讯飞 WebSocket（推荐显式设置 SPARK_API_KEY；若留空则回退到上方 API_KEY 作为签名 key，但 APP_ID/SECRET 必须单独提供）
PROVIDER=xfyun-websocket
SPARK_API_KEY=your-xfyun-api-key
SPARK_APP_ID=your-app-id
SPARK_API_SECRET=your-api-secret
```

> **凭证兼容回退顺序**（按下列优先级取**第一个非空**值）：
> - 讯飞 HTTP 模式（`xfyun-coding` / `xfyun-http`）：`API_KEY` → `SPARK_API_PASSWORD` → `SPARK_API_KEY`
> - 讯飞 WebSocket 模式（`xfyun-websocket`）：`SPARK_API_KEY` → `API_KEY`（仅作为签名 key 的回退，APP_ID / SECRET 必须单独提供）
> - 火山方舟（`volcengine-coding`）：`API_KEY` → `VOLCENGINE_API_KEY` → `ARK_API_KEY`
>
> 推荐只设 `API_KEY` 一个变量，避免歧义。

---

## 二、快速开始

### 1. 安装 uv（如果还没有）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 克隆并进入项目

```bash
git clone https://github.com/htmambo/coding-bridge-mcp.git
cd coding-bridge-mcp
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

> 提示：Coding Bridge MCP 启动时会自动加载当前工作目录下的 `.env` 文件（不覆盖已有的环境变量），所以本地使用时不必手动 `source`。

讯飞 Coding Plan 用户最少只需要：

```env
PROVIDER=xfyun-coding
API_KEY=your-xfyun-key
```

火山方舟 Coding Plan 个人版用户最少只需要：

```env
PROVIDER=volcengine-coding
API_KEY=your-volcano-key
```

### 4. 安装依赖

```bash
uv sync
```

### 5. 接入 Claude Code

**方式 A：本地开发（推荐，方便改配置和二次开发）**

```bash
claude mcp add coding-bridge -s user --transport stdio -- uv run --python 3.12 coding-bridge-mcp
```

**方式 B：直接从 GitHub 安装（无需克隆）**

```bash
claude mcp add coding-bridge -s user --transport stdio -- uvx --from git+https://github.com/htmambo/coding-bridge-mcp.git coding-bridge-mcp
```

> 注意：方式 B 需要你在 Claude Code 配置中注入环境变量（见下文「配置 API Key」），或者从已设置好环境变量的 Shell 启动 Claude Code。

验证：

```bash
claude mcp list
```

应看到 `coding-bridge: uv run --python 3.12 coding-bridge-mcp - ✓ Connected` 或 `coding-bridge: uvx --from git+https://github.com/htmambo/coding-bridge-mcp.git coding-bridge-mcp - ✓ Connected`。

---

## 三、配置 API Key

MCP Server 作为 Claude Code 的子进程运行，需要从环境变量读取密钥。`claude mcp add` 不能直接带 `--env`，推荐通过 `~/.claude/settings.json` 注入：

### 讯飞 Coding Plan（默认）

```json
{
  "mcpServers": {
    "coding-bridge": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/htmambo/coding-bridge-mcp.git",
        "coding-bridge-mcp"
      ],
      "env": {
        "PROVIDER": "xfyun-coding",
        "API_KEY": "your-xfyun-key"
      }
    }
  }
}
```

### 讯飞星火大模型（通用 OpenAI 兼容接口）

```json
{
  "mcpServers": {
    "coding-bridge": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/htmambo/coding-bridge-mcp.git",
        "coding-bridge-mcp"
      ],
      "env": {
        "PROVIDER": "xfyun-http",
        "API_KEY": "your-xfyun-key"
      }
    }
  }
}
```

### 讯飞星火大模型（原生 WebSocket）

WebSocket 模式需要 `SPARK_APP_ID`、`SPARK_API_SECRET` 以及 API 密钥（**优先读取 `SPARK_API_KEY`，留空时回退到通用 `API_KEY`**）。

```json
{
  "mcpServers": {
    "coding-bridge": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/htmambo/coding-bridge-mcp.git",
        "coding-bridge-mcp"
      ],
      "env": {
        "PROVIDER": "xfyun-websocket",
        "SPARK_API_KEY": "your-xfyun-api-key",
        "SPARK_APP_ID": "your-app-id",
        "SPARK_API_SECRET": "your-api-secret"
      }
    }
  }
}
```

> 如需覆盖默认 WebSocket 地址、兼容旧变量（`SPARK_API_PASSWORD` / `SPARK_MODE` 等），可在 `env` 中额外添加对应字段，详见 §1「凭证兼容回退顺序」与 §5 环境变量表。

### 火山方舟 Coding Plan 个人版

```json
{
  "mcpServers": {
    "coding-bridge": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/htmambo/coding-bridge-mcp.git",
        "coding-bridge-mcp"
      ],
      "env": {
        "PROVIDER": "volcengine-coding",
        "API_KEY": "your-volcano-key"
      }
    }
  }
}
```

如果你用的是本地克隆的方式 A，把 `command`/`args` 换成：

```json
{
  "command": "uv",
  "args": ["run", "--python", "3.12", "coding-bridge-mcp"]
}
```

> 注：上方 4 个示例均可按此规则改为本地克隆命令，仅 `command` / `args` 字段需要替换。

> 修改配置后，重启 Claude Code 或运行 `claude mcp list` 刷新。

### 替代方案：从 Shell 启动

如果你用的是 Claude Code CLI，也可以在启动它的 Shell 中导出环境变量：

```bash
export PROVIDER=xfyun-coding
export API_KEY=your-xfyun-key
claude
```

但这种方式对桌面版 Claude 无效，建议优先使用 `settings.json`。

---

## 四、工具说明

### `chat` — 通用多轮对话

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `PROMPT` | `str` | ✅ | 任务指令 |
| `cd` | `Path` | ✅ | 工作目录 |
| `SESSION_ID` | `str` | ❌ | 继续会话，空则新建 |
| `model` | `str` | ❌ | 模型版本；默认取 `PROVIDER` 内置值（`xfyun-coding` → `astron-code-latest`，`xfyun-http` / `xfyun-websocket` → `4.0Ultra`，`volcengine-coding` → `ark-code-latest`），可被 `SPARK_DEFAULT_MODEL` / `VOLCENGINE_MODEL` / `ARK_MODEL` 覆盖 |
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

### `review_code` — 代码审查

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `CODE` | `str` | ✅ | 要审查的代码 |
| `cd` | `Path` | ✅ | 工作目录 |
| `REQUIREMENTS` | `str` | ❌ | 额外要求/上下文 |
| `SESSION_ID` | `str` | ❌ | 继续会话 |
| `model` | `str` | ❌ | 模型版本 |
| `return_all_messages` | `bool` | ❌ | 返回完整历史 |

### `review_plan` — 计划/方案审查

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
| `PROVIDER` | `xfyun-coding` | `xfyun-coding` / `xfyun-http` / `xfyun-websocket` / `volcengine-coding` |
| `API_KEY` | - | 通用 API Key，根据 `PROVIDER` 自动对应到讯飞或火山 |
| `SPARK_MODE` | - | 旧版变量，仍兼容：`coding` / `http` / `websocket` |
| `SPARK_API_PASSWORD` | - | 讯飞 Coding Plan / HTTP 模式的 API Key 或 APIPassword |
| `SPARK_API_KEY` | - | `SPARK_API_PASSWORD` 的别名；WebSocket 签名用 |
| `SPARK_APP_ID` | - | WebSocket 模式 AppID |
| `SPARK_API_SECRET` | - | WebSocket 模式 APISecret |
| `SPARK_API_URL` | 见 Provider | 讯飞 HTTP 端点覆盖 |
| `SPARK_WS_URL` | `wss://spark-api.xf-yun.com/v4.0/chat` | WebSocket 端点覆盖 |
| `SPARK_DEFAULT_MODEL` | 见 Provider | 讯飞默认模型覆盖 |
| `VOLCENGINE_API_KEY` | - | 火山方舟 Coding Plan API Key |
| `VOLCENGINE_API_URL` | 见 Provider | 火山 HTTP 端点覆盖 |
| `VOLCENGINE_MODEL` | `ark-code-latest` | 火山默认模型覆盖 |
| `MCP_TIMEOUT_SECONDS` | `120` | 请求超时（兼容旧 `SPARK_TIMEOUT_SECONDS`） |
| `MCP_MAX_CONTEXT_CHARS` | 见 Provider | 上下文字符上限（兼容旧 `SPARK_MAX_CONTEXT_CHARS`） |
| `MCP_MAX_MESSAGES` | `40` | 单会话最大消息数（兼容旧 `SPARK_MAX_MESSAGES`） |
| `MCP_MAX_TOKENS` | 见 Provider | 单次最大输出 tokens（兼容旧 `SPARK_MAX_TOKENS`） |
| `LOG_LEVEL` | `INFO` | 结构化日志级别（`DEBUG` / `INFO` / `WARNING` / `ERROR`），输出到 stderr |

#### 代理 (PROXY)

默认 `PROXY=false`：忽略 shell 中的 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` 环境变量，强制直连厂商 API。

通过 MCP 启动配置 (`settings.json` → `mcpServers.<name>.env`) 声明：

| `PROXY` | 行为 | 适用场景 |
|---------|------|---------|
| `false` / `no` / `off` / `0` *(默认)* | 直连；httpx `trust_env=False` | 普通部署，无需代理 |
| `true` / `env` / `yes` / `on` / `1` | 读取 shell 中的 `HTTP(S)_PROXY` 环境变量；httpx `trust_env=True` | 已有标准代理出口 |
| `custom` | 使用下方 `HTTP(S)_PROXY_HOST/PORT` 自定义代理 | 需要绕过环境变量、或需要认证 |

`custom` 模式下还支持：

| 变量 | 必填 | 说明 |
|------|------|------|
| `HTTP_PROXY_HOST` | ✅ | HTTP scheme 代理主机 |
| `HTTP_PROXY_PORT` | ✅ | HTTP scheme 代理端口 (1-65535) |
| `HTTP_PROXY_USER` | ❌ | 代理认证用户名；提供时 `HTTP_PROXY_PASSWORD` 必填 |
| `HTTP_PROXY_PASSWORD` | ❌ | 代理认证密码 |
| `HTTPS_PROXY_HOST` | ✅ | HTTPS scheme 代理主机 |
| `HTTPS_PROXY_PORT` | ✅ | HTTPS scheme 代理端口 |
| `HTTPS_PROXY_USER` | ❌ | 同上 |
| `HTTPS_PROXY_PASSWORD` | ❌ | 同上 |

`PROXY=custom` 时 HTTP 与 HTTPS 两组 host/port **必须同时提供**，否则启动期报错。

**settings.json 示例**:

```json
{
  "mcpServers": {
    "coding-bridge": {
      "command": "uv",
      "args": ["run", "coding-bridge-mcp"],
      "env": {
        "PROVIDER": "xfyun-coding",
        "API_KEY": "<your-key>",
        "PROXY": "custom",
        "HTTP_PROXY_HOST": "proxy.internal",
        "HTTP_PROXY_PORT": "8080",
        "HTTPS_PROXY_HOST": "proxy.internal",
        "HTTPS_PROXY_PORT": "8443"
      }
    }
  }
}
```

### Provider 默认值一览

| Provider | `MCP_MAX_CONTEXT_CHARS` | `MCP_MAX_TOKENS` | 备注 |
|---|---|---|---|
| `xfyun-coding` | `96000` | `8192` | 套餐场景，限制最宽 |
| `xfyun-http` | `24000` | `4096` | 通用 HTTP 接口 |
| `xfyun-websocket` | `24000` | `4096` | WebSocket 端点按 model 自动选择 |
| `volcengine-coding` | `128000` | `8192` | 上下文最长 |

> **WebSocket 端点选择规则**（`xfyun-websocket` 模式）：客户端共维护 **4 个 `wss` 端点**，按 `model` 名称映射（当未显式设置 `SPARK_WS_URL` 时）：
>
> | 端点 | 映射的模型 |
> |---|---|
> | `wss://spark-api.xf-yun.com/v4.0/chat` | `4.0Ultra`（未列出模型的默认回退） |
> | `wss://spark-api.xf-yun.com/v3.5/chat` | `generalv3.5`、`max-32k` |
> | `wss://spark-api.xf-yun.com/v3.1/chat` | `generalv3`、`pro-128k` |
> | `wss://spark-api.xf-yun.com/v1.1/chat` | `lite`、`kjwx` |
>
> 未列出的模型会回退到 `v4.0/chat` 端点。建议显式指定 `SPARK_WS_URL` 避免歧义。
>
> ⚠️ **警告**：若未知模型实际不支持 `v4.0/chat` 端点，将导致请求失败。请确保模型名与端点严格匹配。

---

## 六、在 Claude Code 提示词中推荐使用

在 `~/.claude/CLAUDE.md` 中加入类似内容，可让 Claude Code 在编码流程中主动调用审查工具：

```markdown
## Coding Bridge MCP 使用规范

1. 在形成初步实现思路后，可调用 `review_plan` 审查实施计划。
2. 完成代码修改后，必须调用 `review_code` 审查改动。
3. 保存每次返回的 `SESSION_ID`，以便对同一话题进行多轮追问。
4. 星火/Coding Plan 的回复仅供参考，你仍需保持独立判断。
```

---

## 七、常见问题

**Q: Coding Plan 返回 401 怎么办？**

- 确认 API Key 来自「套餐订阅」页面，而不是星火大模型控制台。
- 确认 `PROVIDER=xfyun-coding`（或 `SPARK_MODE=coding`）。
- 确认 model 使用 `astron-code-latest`（默认）。

**Q: Coding Plan 返回 403 怎么办？**

- 鉴权 URL 签名（WebSocket 模式）依赖 `SPARK_API_KEY`（或 `API_KEY`）和 `SPARK_API_SECRET`，三者必须来自同一应用。
- 火山方舟 403 通常是 endpoint 不存在或模型名拼写错误，先确认 `ark-code-latest` 仍可访问。

**Q: 模型底层怎么切换？**

在 [讯飞星辰 MaaS 套餐订阅页面](https://maas.xfyun.cn/packageSubscription) 点击「配置模型」，1-3 分钟后生效。API 层仍使用 `astron-code-latest`。

**Q: 出现 429 / 请求速率限制？**

Coding Plan 有 5 小时/周/月的请求次数限制，高峰期也可能触发平台限流。代码已透传错误信息，建议稍后重试或升级套餐。

**Q: 调用时提示 `Working directory does not exist`？**

当前涉及文件系统操作的工具会校验 `cd` 参数必须为**已存在的真实目录**，若目录不存在将拒绝执行。CI / 沙箱环境务必先 `mkdir -p` 工作目录。

**Q: 如何调试（查看完整消息历史）？**

调用任意工具时传 `return_all_messages=True`，响应中会带 `all_messages` 字段返回当前会话全部消息。注意：`SESSION_ID` 对应的会话上下文保存在进程内存字典中，服务进程重启后内存清空，旧 `SESSION_ID` 即失效，需获取新 ID 开启新会话。

**Q: 为什么修改了 `.env` 文件中的凭证，但依然提示鉴权失败？**

应用加载 `.env` 文件时**不覆盖**已存在的系统环境变量（`override=False`），即**系统环境变量的优先级始终高于 `.env`**。请检查 Shell / CI 配置中是否设置了旧凭证。

---

## 八、开发与测试

```bash
# 安装 dev 依赖
uv sync

# 运行测试
uv run pytest

# 直接以 stdio 方式启动服务器（便于手动调试）
uv run coding-bridge-mcp
```

测试覆盖：`tests/test_config.py`（Provider 解析 / 凭证回退 / 配置校验）、`tests/test_session.py`（消息历史裁剪）。所有工具的真实调用都通过 mock，不会产生 API 费用。

修改代码后建议先跑一遍 `pytest` 再提交。

---

## 九、许可证

MIT
