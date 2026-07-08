# Coding Bridge MCP

基于 [MCP 协议](https://modelcontextprotocol.io) 封装的多厂商 **Coding Plan** 服务，目前已支持讯飞星火 / 讯飞星辰 Coding Plan、火山方舟 Coding Plan 个人版、百度智能云千帆 Coding Plan、商汤日日新 SenseNova Token Plan 与 DeepSeek 官方 API，并为 OpenCode Go（experimental）提供 OpenAI 兼容子集接入，为 Claude Code 等 AI 编程工具提供代码审查、计划审查与多轮对话能力。

---

## 一、支持的 Provider

Coding Bridge MCP 通过统一的 OpenAI 兼容 HTTP 客户端接入多个厂商的 Coding Plan / 大模型服务。

| Provider | 协议 | 凭证 | 默认端点 | 默认模型 |
|----------|------|------|----------|----------|
| **xfyun-coding**（默认） | OpenAI 兼容 | `API_KEY`（HTTP Bearer） | `https://maas-coding-api.cn-huabei-1.xf-yun.com/v2/chat/completions` | `astron-code-latest` |
| **volcengine-coding** | OpenAI 兼容 | `API_KEY`（HTTP Bearer） | `https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions` | `ark-code-latest` |
| **qianfan-coding** | OpenAI 兼容 | `API_KEY`（HTTP Bearer） | `https://qianfan.baidubce.com/v2/coding/chat/completions` | `qianfan-code-latest` |
| **sensenova** ⚠️ 配额极低 | OpenAI 兼容 | `API_KEY`（HTTP Bearer） | `https://token.sensenova.cn/v1/chat/completions` | `deepseek-v4-flash` |
| **deepseek** | OpenAI 兼容 | `API_KEY`（HTTP Bearer） | `https://api.deepseek.com/chat/completions` | `deepseek-v4-pro` |
| **opencode-go** ⚠️ experimental | OpenAI 兼容 | `API_KEY`（HTTP Bearer） | `https://opencode.ai/zen/go/v1/chat/completions` | `glm-5.2` |

> **注意**：Coding Plan 类套餐（讯飞、火山）的 API Key **仅限在 AI 编程工具交互场景中使用**，禁止用于自动化脚本、批量任务或自建后端。

切换 Provider 只需修改 `PROVIDER` 环境变量（旧版 `SPARK_MODE` 仍兼容）。为统一凭证入口，推荐使用通用变量 `API_KEY`：

```env
# 讯飞 Coding Plan
PROVIDER=xfyun-coding
API_KEY=your-xfyun-key

# 火山方舟 Coding Plan 个人版
PROVIDER=volcengine-coding
API_KEY=your-volcano-key

# 百度智能云千帆 Coding Plan（OpenAI 兼容）
PROVIDER=qianfan-coding
API_KEY=your-qianfan-key

# 商汤日日新 SenseNova（Token Plan，OpenAI 兼容，⚠️ 配额极低）
PROVIDER=sensenova
API_KEY=your-sensenova-key

# DeepSeek 官方 API（OpenAI 兼容）
PROVIDER=deepseek
API_KEY=your-deepseek-key

# OpenCode Go（⚠️ experimental，OpenAI 兼容子集：GLM / Kimi / DeepSeek / MiMo）
PROVIDER=opencode-go
API_KEY=your-opencode-go-key
```

> **凭证兼容回退顺序**（按下列优先级取**第一个非空**值）：
> - 讯飞 Coding Plan（`xfyun-coding`）：`API_KEY` → `SPARK_API_PASSWORD` → `SPARK_API_KEY`
> - 火山方舟（`volcengine-coding`）：`API_KEY` → `VOLCENGINE_API_KEY` → `ARK_API_KEY`
> - 千帆 Coding Plan（`qianfan-coding`）：`API_KEY` → `QIANFAN_API_KEY`
> - 商汤 SenseNova（`sensenova`）：`API_KEY` → `SENSENOVA_API_KEY`
> - DeepSeek（`deepseek`）：`API_KEY` → `DEEPSEEK_API_KEY`
> - OpenCode Go（`opencode-go`）：`API_KEY` → `OPENCODE_API_KEY`
>
> 推荐只设 `API_KEY` 一个变量，避免歧义。

> **⚠️ 关于 `opencode-go`（experimental）**：官方文档仅描述 TUI `/connect` 与 JS AI SDK 用法，**未明确直接 HTTP/REST 调用契约**。本 Provider 按 OpenAI 兼容惯例推断 `Authorization: Bearer` 鉴权——**首次使用前建议用 curl 实测确认**，若返回 401/403 需排查是否实际要求 `x-api-key` 等其他头。仅覆盖 OpenAI 兼容子集（GLM / Kimi / DeepSeek / MiMo）；MiniMax / Qwen 走 Anthropic 协议，暂不支持。额度为美元配额制（每 5h $12 / 周 $30 / 月 $60）。
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

OpenCode Go 用户最少只需要（⚠️ experimental）：

```env
PROVIDER=opencode-go
API_KEY=your-opencode-go-key
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

### 接入 Kimi Code

Kimi Code 通过 `~/.kimi-code/mcp.json` 声明 MCP Server（也支持项目级 `.kimi-code/mcp.json`，优先级更高）。创建或编辑该文件，加入以下内容：

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

> 注意：当前 Kimi Code 的 MCP 配置主要通过直接编辑 `~/.kimi-code/mcp.json` 完成。修改后需要重启 Kimi 会话或启动新会话才会加载。

验证：重启 Kimi 后，新会话中应出现 `mcp__coding-bridge__chat`、`mcp__coding-bridge__review_code` 等工具。

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

### 百度智能云千帆 Coding Plan（OpenAI 兼容）

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
        "PROVIDER": "qianfan-coding",
        "API_KEY": "your-qianfan-key"
      }
    }
  }
}
```

### 商汤日日新 SenseNova（Token Plan，OpenAI 兼容）

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
        "PROVIDER": "sensenova",
        "API_KEY": "your-sensenova-key"
      }
    }
  }
}
```

> 默认模型 `deepseek-v4-flash`（1M 上下文，思考模式，审查质量较高）。⚠️ **Token Plan 配额极低**（tpm 限流易触发，连续调用需间隔约 1 分钟）；若更看重吞吐而非审查深度，可设 `SENSENOVA_MODEL=sensenova-6.7-flash-lite`（256K 上下文，更快更省 token）。注意 `sensenova-u1-fast` 是图像生成接口，不能作对话模型。

### DeepSeek 官方 API（OpenAI 兼容）

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
        "PROVIDER": "deepseek",
        "API_KEY": "your-deepseek-key"
      }
    }
  }
}
```

> 默认模型 `deepseek-v4-pro`（思考模式，审查质量更高）；如需更快更省 token，可设 `DEEPSEEK_MODEL=deepseek-v4-flash`。旧名 `deepseek-chat` / `deepseek-reasoner` 将于 2026-07-24 废弃（分别对应 `deepseek-v4-flash` 的非思考 / 思考模式）。思考模式响应含 `reasoning_content`，客户端只取最终 `content`（符合审查工具预期）。

### OpenCode Go（⚠️ experimental）

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
        "PROVIDER": "opencode-go",
        "API_KEY": "your-opencode-go-key"
      }
    }
  }
}
```

### Kimi Code（`~/.kimi-code/mcp.json`）

Kimi Code 的 MCP 配置与 Claude Code 的 `settings.json` 结构相同，只是把文件放到 `~/.kimi-code/mcp.json`。各 Provider 配置示例如下。

#### 讯飞 Coding Plan（默认）

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

#### 火山方舟 Coding Plan 个人版

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

#### 百度智能云千帆 Coding Plan

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
        "PROVIDER": "qianfan-coding",
        "API_KEY": "your-qianfan-key"
      }
    }
  }
}
```

#### 商汤日日新 SenseNova（Token Plan）

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
        "PROVIDER": "sensenova",
        "API_KEY": "your-sensenova-key"
      }
    }
  }
}
```

#### DeepSeek 官方 API（OpenAI 兼容）

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
        "PROVIDER": "deepseek",
        "API_KEY": "your-deepseek-key"
      }
    }
  }
}
```

#### OpenCode Go（⚠️ experimental）

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
        "PROVIDER": "opencode-go",
        "API_KEY": "your-opencode-go-key"
      }
    }
  }
}
```

> 提示：Kimi Code 暂不支持全局 `AGENTS.md`，自动审查规范需要放在**项目根目录**的 `AGENTS.md` 中，详见 §6。

如果你用的是本地克隆的方式 A，把 `command`/`args` 换成：

```json
{
  "command": "uv",
  "args": ["run", "--python", "3.12", "coding-bridge-mcp"]
}
```

> 注：以上 Claude Code 与 Kimi Code 示例中的 `uvx --from git+...` 均可按此规则改为本地克隆命令，仅 `command` / `args` 字段需要替换。

> 修改 Claude Code 配置后，重启 Claude Code 或运行 `claude mcp list` 刷新；修改 Kimi Code 的 `~/.kimi-code/mcp.json` 后，重启 Kimi 会话即可。

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
| `model` | `str` | ❌ | 模型版本；默认取 `PROVIDER` 内置值（`xfyun-coding` → `astron-code-latest`，`volcengine-coding` → `ark-code-latest`），可被 `SPARK_DEFAULT_MODEL` / `VOLCENGINE_MODEL` / `ARK_MODEL` 覆盖 |
| `return_all_messages` | `bool` | ❌ | 是否返回完整历史 |

返回值：

```json
{
  "success": true,
  "SESSION_ID": "uuid-string",
  "agent_messages": "模型回复内容...",
  "usage": {
    "prompt_tokens": 100,
    "completion_tokens": 200,
    "total_tokens": 300,
    "cached_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  },
  "cumulative_usage": {
    "prompt_tokens": 350,
    "completion_tokens": 540,
    "total_tokens": 890,
    "cached_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  }
}
```

`usage` 是**当前这一轮**的 token 用量，`cumulative_usage` 是该会话从开始到现在的累计值（跨多轮对话自动累加）。当 `SESSION_ID` 沿用同一个时，累计值会持续增长。

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

### `get_token_stats` — 查询 token 用量统计

读取当前 MCP 进程内**已累计**的 token 用量。所有写操作工具（`chat` / `review_code` / `review_plan`）在每次成功调用后都会把 `usage` 累加到对应会话；本工具不发起任何 HTTP 请求。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `cd` | `Path` | ✅ | 工作目录 |
| `SESSION_ID` | `str` | ❌ | 指定会话 ID；空字符串或不传则汇总当前进程所有会话 |

返回值（指定 `SESSION_ID` 时）：

```json
{
  "success": true,
  "SESSION_ID": "uuid-string",
  "found": true,
  "cumulative_usage": {
    "prompt_tokens": 350,
    "completion_tokens": 540,
    "total_tokens": 890,
    "cached_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  }
}
```

返回值（不传 `SESSION_ID`，全局汇总）：

```json
{
  "success": true,
  "cumulative_usage": {
    "prompt_tokens": 1280,
    "completion_tokens": 960,
    "total_tokens": 2240,
    "cached_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  },
  "session_count": 3,
  "sessions": {
    "uuid-a": { "prompt_tokens": 350, "...": "..." },
    "uuid-b": { "...": "..." },
    "uuid-c": { "...": "..." }
  }
}
```

> **关于缓存三件套**：`cached_tokens` / `cache_creation_input_tokens` / `cache_read_input_tokens` 是 Anthropic 风格的统一 schema。当前 `volcengine-coding` 与 `xfyun-coding` 默认不启用上下文缓存，所以通常为 0；`cached_tokens` 会在厂商返回 `usage.prompt_tokens_details.cached_tokens` 或顶层 `cached_tokens` 时如实透传。Schema 稳定后，未来即便切换到真正支持缓存的 Provider，调用方代码也无需调整。

---

## 五、环境变量完整列表

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PROVIDER` | `xfyun-coding` | `xfyun-coding` / `volcengine-coding` / `qianfan-coding` / `sensenova` / `deepseek` / `opencode-go` |
| `API_KEY` | - | 通用 API Key，根据 `PROVIDER` 自动对应到讯飞、火山、千帆、商汤或 DeepSeek |
| `SPARK_MODE` | - | 旧版变量，已废弃；`coding` 映射到 `xfyun-coding`（仍发出弃用警告），`http` / `websocket` 不再支持并会报错，请直接使用 `PROVIDER` |
| `SPARK_API_PASSWORD` | - | 讯飞 Coding Plan 的 API Key 或 APIPassword |
| `SPARK_API_KEY` | - | `SPARK_API_PASSWORD` 的别名 |
| `SPARK_API_URL` | 见 Provider | 讯飞 HTTP 端点覆盖 |
| `SPARK_DEFAULT_MODEL` | 见 Provider | 讯飞默认模型覆盖 |
| `VOLCENGINE_API_KEY` | - | 火山方舟 Coding Plan API Key |
| `ARK_API_KEY` | - | 火山方舟旧版 API Key（`VOLCENGINE_API_KEY` 的别名） |
| `VOLCENGINE_API_URL` | 见 Provider | 火山 HTTP 端点覆盖 |
| `VOLCENGINE_MODEL` | `ark-code-latest` | 火山默认模型覆盖 |
| `QIANFAN_API_KEY` | - | 千帆 Coding Plan API Key（`API_KEY` 为空时回退） |
| `QIANFAN_API_URL` | 见 Provider | 千帆 Coding Plan 端点覆盖 |
| `QIANFAN_MODEL` | `qianfan-code-latest` | 千帆默认模型覆盖 |
| `SENSENOVA_API_KEY` | - | 商汤 SenseNova API Key（`API_KEY` 为空时回退） |
| `SENSENOVA_API_URL` | 见 Provider | 商汤 SenseNova 端点覆盖 |
| `SENSENOVA_MODEL` | `deepseek-v4-flash` | 商汤默认模型覆盖（可选 `sensenova-6.7-flash-lite`，配额极低时换用以提吞吐） |
| `DEEPSEEK_API_KEY` | - | DeepSeek 官方 API Key（`API_KEY` 为空时回退） |
| `DEEPSEEK_API_URL` | 见 Provider | DeepSeek 端点覆盖 |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | DeepSeek 默认模型覆盖（可选 `deepseek-v4-flash`） |
| `OPENCODE_API_KEY` | - | OpenCode Go API Key（`API_KEY` 为空时回退） |
| `OPENCODE_API_URL` | 见 Provider | OpenCode Go 端点覆盖 |
| `OPENCODE_MODEL` | `glm-5.2` | OpenCode Go 默认模型覆盖 |
| `MCP_TIMEOUT_SECONDS` | `300` | 请求超时（兼容旧 `SPARK_TIMEOUT_SECONDS`） |
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
| `volcengine-coding` | `128000` | `8192` | 上下文最长 |
| `qianfan-coding` | `96000` | `8192` | 默认值保守估计，可由 `MCP_MAX_CONTEXT_CHARS` 覆盖 |
| `sensenova` | `96000` | `8192` | ⚠️ 配额极低；默认 `deepseek-v4-flash`（1M 上下文，思考模式），此处按保守字符数估计，可由 `MCP_MAX_CONTEXT_CHARS` 覆盖 |
| `deepseek` | `96000` | `8192` | 默认 `deepseek-v4-pro`（思考模式）；字符数按保守估计，可由 `MCP_MAX_CONTEXT_CHARS` 覆盖 |
| `opencode-go` | `96000` | `8192` | ⚠️ experimental；GLM-5.2 上下文长度未公开，保守估计，可由 `MCP_MAX_CONTEXT_CHARS` 覆盖 |

---

## 六、在 Claude Code / Kimi Code 提示词中推荐使用

### Claude Code：全局 `~/.claude/CLAUDE.md`

在 `~/.claude/CLAUDE.md` 中加入类似内容，可让 Claude Code 在编码流程中主动调用审查工具：

```markdown
## Coding Bridge MCP 使用规范

1. 在形成初步实现思路后，可调用 `review_plan` 审查实施计划。
2. 完成代码修改后，必须调用 `review_code` 审查改动。
3. 保存每次返回的 `SESSION_ID`，以便对同一话题进行多轮追问。
4. 星火/Coding Plan 的回复仅供参考，你仍需保持独立判断。
```

### Kimi Code：项目级 `AGENTS.md`

Kimi Code **没有全局 AGENTS.md**，它只从项目树中读取 `AGENTS.md` / `.kimi/AGENTS.md` / `agents.md`。因此自动审查规范必须放在**每个项目的根目录**。

在当前项目根目录创建 `AGENTS.md`，内容示例：

```markdown
# Coding Bridge MCP 自动审查规范

## 1. 计划审查（形成思路后）

调用 `mcp__coding-bridge__review_plan`：
- `PLAN`：当前实现计划文本
- `cd`：当前项目根目录
- `CONTEXT`：项目背景与约束（可选）

## 2. 代码审查（完成修改后）

**每次对 `src/`、`tests/` 做出实质性修改后，必须调用 `mcp__coding-bridge__review_code`：**
- `CODE`：需要审查的完整代码或 diff
- `cd`：当前项目根目录
- `REQUIREMENTS`：额外上下文（可选）

## 3. 多轮追问

保存每次返回的 `SESSION_ID`，对同一话题继续追问时沿用该 ID。

## 4. 判断原则

Coding Plan / 星火返回的审查结论仅供参考，你仍需保持独立判断。
```

> 注意：`AGENTS.md` 在会话启动时读取，修改后需要**重启 Kimi 会话**才会生效。
>
> 如果需要在多个项目复用同一份规范，可在 `~/.kimi-code/templates/AGENTS.md` 维护一份母版，新建项目时复制进去。Kimi Code 不会读取 `~/.kimi-code/AGENTS.md`。

---

## 七、与 XPowers 联合使用

XPowers 提供「结构化工作流 + 内部多 Agent 验证」，coding-bridge 提供「外部 Coding Plan 专家级审查」。两者可以互补：XPowers 负责计划、跟踪、内部验证；coding-bridge 负责外部代码/计划审查。

### 最简单的联合方式：AGENTS.md + XPowers 共存

保留项目根目录的 `AGENTS.md`（要求改完代码后调用 `mcp__coding-bridge__review_code`），同时安装 XPowers。Kimi 会同时读取 XPowers skills 和 `AGENTS.md`，模型通常会按以下流程执行：

```
形成思路
  ↓
XPowers write-plan → 生成实现计划
  ↓
实现代码
  ↓
AGENTS.md 触发 → coding-bridge review_code（外部审查）
  ↓
XPowers test-runner → 运行测试
  ↓
XPowers review-implementation → 对照需求检查
  ↓
XPowers verification-before-completion → 最终确认
  ↓
任务完成
```

### 把 coding-bridge 嵌入 XPowers verification 流程

如果你希望 XPowers 的 verification **明确强制**调用 coding-bridge，可以在 XPowers 的 skill 或自定义 skill 中加入以下步骤：

```markdown
## 外部 Coding Plan 审查

在完成内部 review-implementation 和测试后，调用：

- `mcp__coding-bridge__review_code`
  - `CODE`: 本次修改的完整代码或 diff
  - `cd`: 项目根目录
  - `REQUIREMENTS`: 原始需求、已发现的内部审查问题

将 coding-bridge 返回的风险和建议作为验收依据之一。
```

> 注意：直接修改 `~/.kimi-code/skills/` 下的 XPowers skill 文件会在更新时被覆盖。建议复制到项目级 `.kimi-code/skills/` 做覆盖，或创建独立自定义 skill。

### 自定义 skill 示例

在项目 `.kimi-code/skills/coding-bridge-review/SKILL.md` 中创建：

```markdown
---
name: coding-bridge-review
description: Use when you need an external Coding Plan review after implementing code changes.
---

# Coding Bridge Review

When verification is needed:

1. Collect the changed code or diff.
2. Call `mcp__coding-bridge__review_code` with `cd` set to project root.
3. Summarize findings and decide if fixes are needed.
4. If fixes are made, repeat the review.
```

然后在 `AGENTS.md` 中加上：

```markdown
完成代码修改后，优先调用 `coding-bridge-review` skill 进行外部 Coding Plan 审查。
```

### 注意事项

- **成本叠加**：XPowers 内部多 Agent 审查 + coding-bridge 外部审查会同时消耗模型 token 和 Coding Plan 套餐额度。
- **结论冲突**：如果 XPowers 内部审查与 coding-bridge 结论冲突，可在 `AGENTS.md` 中写明优先级，例如「以 coding-bridge 的安全与架构建议为最终依据」。
- **避免重复**：XPowers 内部 reviewer 负责基础检查，coding-bridge 负责外部视角的深层问题，分工更合理。

---

## 八、常见问题

**Q: Coding Plan 返回 401 怎么办？**

- 确认 API Key 来自「套餐订阅」页面，而不是星火大模型控制台。
- 确认 `PROVIDER=xfyun-coding`。
- 确认 model 使用 `astron-code-latest`（默认）。

**Q: Coding Plan 返回 403 怎么办？**

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

**Q: 调用 coding-bridge 超时或被中途打断，超时在哪里设置？**

超时分两层，两者都需调到足够大且相互匹配：

1. **客户端层（Claude Code / Kimi Code → coding-bridge 工具调用）**：由 MCP 宿主对单次工具调用的超时控制。
   - **Claude Code**：默认 `MCP_TOOL_TIMEOUT` 约 28 小时，基本不会超时；coding-bridge 为 stdio 类型，不受 5 分钟空闲断开（`CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`，仅针对 HTTP/SSE）影响。如需显式上调，在 `~/.claude.json` 的 `coding-bridge` 块加 `timeout`（单位毫秒），仅对该服务生效，改完**重启 Claude Code**。
   - **Kimi Code**：默认 `toolTimeoutMs` 为 **30000 毫秒（30 秒）**，审长代码或复杂计划时容易触发 `-32001: Request timed out`。在 `~/.kimi-code/mcp.json`（或项目级 `.kimi-code/mcp.json`）对应 server 条目中添加 `toolTimeoutMs` 即可调整，改完**重启 Kimi 会话**。`startupTimeoutMs` 控制 server 启动/连接超时，默认同样 30000 毫秒，首次 `uvx` 拉取构建较慢时也可能需要上调。
2. **服务端层（coding-bridge → 上游 LLM）**：由 `MCP_TIMEOUT_SECONDS`（旧名 `SPARK_TIMEOUT_SECONDS`）控制，**默认 300 秒**（经多轮及高峰期实测，120 秒在上游 LLM 高负载时易被打断），超过即被 `httpx` 打断（见 `src/coding_bridge_mcp/config.py`）。
   - `uvx` 从 git 启动时不会加载仓库 `.env`，需在宿主配置（`~/.claude.json` 或 `~/.kimi-code/mcp.json`）的 `env` 字段显式传入才可靠。

建议客户端超时 ≤ 服务端超时，避免宿主未放弃时 coding-bridge 已因上游超时报错：

**Claude Code 示例：**

```jsonc
"coding-bridge": {
  "type": "stdio",
  "command": "uvx",
  "args": ["--from", "git+https://github.com/htmambo/coding-bridge-mcp.git", "coding-bridge-mcp"],
  "timeout": 600000,                       // 客户端层：10 分钟等待工具返回
  "env": {
    "PROVIDER": "volcengine-coding",
    "API_KEY": "ark-...",
    "MCP_TIMEOUT_SECONDS": "600"           // 服务端层：10 分钟等待上游 LLM
  }
}
```

**Kimi Code 示例：**

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
        "API_KEY": "ark-...",
        "MCP_TIMEOUT_SECONDS": "600"
      },
      "startupTimeoutMs": 60000,
      "toolTimeoutMs": 300000
    }
  }
}
```

---

## 九、更新方式

通过 `claude mcp add` 安装后，命令注册在 Claude Code 配置中固定不变。更新 = 让 `claude` 启动时重新拉取新版本。

### 方式 A：清 uvx 缓存（推荐，适合远端已 push 的场景）

`uvx --from git+...` 会带缓存窗口拉取远端源。清掉本地 wheel 缓存即可让下次启动重新 fetch。

```bash
# 清掉 coding-bridge-mcp 的 wheel 缓存
uv cache clean coding-bridge-mcp

# 重新启动 Claude，下次启动会自动拉取最新 main 分支
```

> 适用于：日常维护，远端 `main` 分支已有目标提交，本地无需修改。

### 方式 B：临时切到本地 checkout（适合开发调试）

跳过 uvx + git 拉取，直接用本地仓库的 `.venv` 跑。任何本地修改立即生效，无需 push。

```bash
# 1. 移除旧的远端源注册
claude mcp remove coding-bridge

# 2. 重新注册为本地路径
claude mcp add coding-bridge -s user --transport stdio -- \
  uv run --directory /home/hoping/htdocs/coding-bridge-mcp coding-bridge-mcp
```

> 适用于：本地有未推送的提交、需要立刻在 Claude 中验证最新代码改动。

### 方式 C（可选）：锁版本到 commit / tag

对生产部署建议锁定到具体版本，避免 main 分支意外变更影响线上行为。

```bash
# 第一次 add 时直接锁版本
claude mcp add coding-bridge -s user --transport stdio -- \
  uvx --from git+https://github.com/htmambo/coding-bridge-mcp.git@<commit-sha> coding-bridge-mcp

# 锁到 tag
claude mcp add coding-bridge -s user --transport stdio -- \
  uvx --from git+https://github.com/htmambo/coding-bridge-mcp.git@v0.2.0 coding-bridge-mcp
```

更新时把 `@<sha>` 换成新值，重新执行 `claude mcp add`（同名会覆盖）。

### 调试与验证

```bash
# 查看当前 MCP server 注册的命令
claude mcp get coding-bridge

# 直接运行看 uvx 是否拉到新版本
uvx --from git+https://github.com/htmambo/coding-bridge-mcp.git coding-bridge-mcp --help

# 看实际拉取的 commit
uvx --from git+https://github.com/htmambo/coding-bridge-mcp.git@main \
  python -c "import coding_bridge_mcp; print(coding_bridge_mcp.__file__)"
```

---

## 十、开发与测试

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

## 十一、许可证

MIT
