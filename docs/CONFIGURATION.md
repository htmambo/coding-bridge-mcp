# Coding Bridge MCP 配置说明

本文档基于 2026-07-23 对当前仓库的代码、文档和本地应用配置的检查结果整理。
推荐把 Claude Code / Kimi Code 的 MCP 配置文件作为运行时唯一配置源；仓库根目录的
`.env` 只用于本地 checkout 直接启动和测试，不建议作为远程 `uvx` 部署的配置入口。

## 1. 推荐配置方式

### Kimi Code

项目级配置文件为 `.kimi-code/mcp.json`，当前仓库已有该文件。示例：

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
        "QIANFAN_API_KEY": "<qianfan-api-key>",
        "MCP_TIMEOUT_SECONDS": "300",
        "MCP_MAX_MESSAGES": "40",
        "MCP_MAX_TOKENS": "8192",
        "PROXY": "false",
        "LOG_LEVEL": "INFO"
      },
      "startupTimeoutMs": 300000,
      "toolTimeoutMs": 300000
    }
  }
}
```

如果使用本地 checkout，将 `command`/`args` 换成：

```json
{
  "command": "uv",
  "args": [
    "run",
    "--directory",
    "/absolute/path/to/coding-bridge-mcp",
    "coding-bridge-mcp"
  ]
}
```

### Claude Code

Claude Code 的 MCP 注册通常由 `claude mcp add` 管理，配置最终位于 Claude 的 MCP
配置中（常见位置为 `~/.claude.json`）。手工配置时，使用与 Kimi 相同的
`mcpServers.coding-bridge.env` 结构：

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
        "VOLCENGINE_API_KEY": "<volcengine-api-key>",
        "MCP_TIMEOUT_SECONDS": "300",
        "PROXY": "false",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Claude/Kimi 的应用配置会把 `env` 直接注入 MCP 子进程。子进程环境中的变量优先于
`.env` 中的同名变量，因此应用配置是推荐的主入口。

## 2. 总体优先级

必须区分两层优先级：先合并环境来源，再解析同一配置项的回退链。

```text
应用配置 env / Shell 导出的进程环境
    > .env 中的同名变量（load_dotenv override=False）
    > 当前 Provider 的回退变量顺序
    > Provider profile 的内置默认值
```

更精确地说：

1. `server.py` 导入时调用 `load_dotenv(override=False)`。同名进程环境变量不会被 `.env`
   覆盖。
2. 合并后的环境变量交给 `config._env()`，它按列表顺序返回第一个非空值。
3. 进程环境的优先级是“同名优先”；不同名称仍按 Provider 回退链决定。例如 `.env`
   中已有 `API_KEY`，而应用配置设置了 `QIANFAN_API_KEY`，最终会取
   `QIANFAN_API_KEY`，因为 Provider 专用变量排在通用变量前面。
4. 空字符串不算有效值。除 Provider 选择外，普通字符串不会自动去除首尾空格。
5. 配置在模块导入时读取，修改应用配置或 `.env` 后需要重启 MCP 进程。

如果 Claude Code 和 Kimi Code 都配置了 Coding Bridge，不存在两套配置在进程内继续
叠加的情况；实际生效的是当前启动该 MCP 进程的那个应用配置。

## 3. Provider 选择

Provider 选择顺序为：

```text
PROVIDER > SPARK_MODE（旧兼容变量） > xfyun-coding
```

支持的值：

| Provider | 默认 API URL | 默认模型 |
|---|---|---|
| `xfyun-coding` | `https://maas-coding-api.cn-huabei-1.xf-yun.com/v2/chat/completions` | `astron-code-latest` |
| `volcengine-coding` | `https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions` | `ark-code-latest` |
| `qianfan-coding` | `https://qianfan.baidubce.com/v2/tokenplan/personal/chat/completions` | `glm-5.2` |
| `opencode-go` | `https://opencode.ai/zen/go/v1/chat/completions` | `glm-5.2` |
| `sensenova` | `https://token.sensenova.cn/v1/chat/completions` | `deepseek-v4-flash` |
| `deepseek` | `https://api.deepseek.com/chat/completions` | `deepseek-v4-pro` |

`SPARK_MODE=coding` 仍可工作，但会产生弃用警告。`SPARK_MODE=http` 和
`SPARK_MODE=websocket` 已不再支持；无效的 `PROVIDER` 不会回退到默认值，而是报错。

## 4. 凭证、URL 和模型优先级

### 凭证

所有 Provider 都支持专用凭证变量和通用 `API_KEY`。专用变量优先，`API_KEY` 仅作兜底：

| Provider | 凭证回退顺序 |
|---|---|
| `xfyun-coding` | `SPARK_API_KEY` > `API_KEY` |
| `volcengine-coding` | `VOLCENGINE_API_KEY` > `API_KEY` |
| `qianfan-coding` | `QIANFAN_API_KEY` > `API_KEY` |
| `opencode-go` | `OPENCODE_API_KEY` > `API_KEY` |
| `sensenova` | `SENSENOVA_API_KEY` > `API_KEY` |
| `deepseek` | `DEEPSEEK_API_KEY` > `API_KEY` |

### URL

URL 只使用当前 Provider 声明的变量：

```text
SPARK_API_URL
VOLCENGINE_API_URL > ARK_API_URL
QIANFAN_API_URL
OPENCODE_API_URL
SENSENOVA_API_URL
DEEPSEEK_API_URL
```

未设置时使用 Provider profile 的默认 URL。没有通用的 `MCP_API_URL`。

### 模型

工具调用中的 `model` 参数优先级最高；为空时使用环境变量，再回退到 profile 默认值：

```text
工具 model 参数
    > Provider 模型变量
    > Provider 默认模型
```

模型变量为 `SPARK_DEFAULT_MODEL`、`VOLCENGINE_MODEL`/`ARK_MODEL`、
`QIANFAN_MODEL`、`OPENCODE_MODEL`、`SENSENOVA_MODEL` 和 `DEEPSEEK_MODEL`。

## 5. 通用运行参数

| 新变量 | 旧兼容变量 | 默认值 | 作用 |
|---|---|---:|---|
| `MCP_TIMEOUT_SECONDS` | `SPARK_TIMEOUT_SECONDS` | `300` | 上游 HTTP 请求超时，单位秒 |
| `MCP_MAX_CONTEXT_CHARS` | `SPARK_MAX_CONTEXT_CHARS` | `1,048,576` | 当前 Provider 的会话历史字符上限 |
| `MCP_MAX_MESSAGES` | `SPARK_MAX_MESSAGES` | `40` | 单会话最大消息条数 |
| `MCP_MAX_TOKENS` | `SPARK_MAX_TOKENS` | `8,192` | HTTP 请求中的 `max_tokens` |
| `LOG_LEVEL` | 无 | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`，输出到 stderr |

通用参数的优先级为：

```text
MCP_* > SPARK_* > Provider 默认值
```

上下文和消息裁剪发生在服务端内存会话中；模型 API 本身的真实上下文上限仍由厂商
决定，代码中的字符数是发送前的保护阈值。

## 6. 代理配置

`PROXY` 默认值是 `false`：强制直连，并忽略宿主 Shell 的标准代理变量。

| `PROXY` 值 | 实际行为 |
|---|---|
| `false`/`no`/`off`/`0` | `httpx trust_env=False`，直连 |
| `true`/`yes`/`on`/`1`/`env` | `httpx trust_env=True`，使用 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 等 |
| `custom` | 使用显式代理，不读取宿主环境代理 |

`custom` 必须同时提供：

```text
HTTP_PROXY_HOST + HTTP_PROXY_PORT
HTTPS_PROXY_HOST + HTTPS_PROXY_PORT
```

端口必须在 `1-65535` 范围内。代理认证变量为对应 scheme 的
`*_PROXY_USER` 和 `*_PROXY_PASSWORD`。代码禁止只提供 PASSWORD，但允许只提供 USER；
这点与部分旧文档中“必须成对”的描述不同。

## 7. 启动和工具行为

- 配置加载发生在 `server.py` 导入阶段。
- API 客户端在第一次 `chat`、`review_code` 或 `review_plan` 调用时懒加载。
- API Key 缺失、Provider 无效或代理配置不完整会导致工具返回配置错误。
- `chat`、`review_code`、`review_plan` 都可以显式指定 `model`。
- `SESSION_ID` 只复用当前进程内存中的会话，不会重新加载配置。
- `get_token_stats` 只读取当前进程统计，不发起上游 HTTP 请求。
- 客户端的启动/工具超时与 `MCP_TIMEOUT_SECONDS` 是两层独立设置；实际等待时间受较早触发的那一层限制。

## 8. 当前仓库状态和风险

### 当前实际配置冲突

- 根目录 `.env` 当前选择 `qianfan-coding`。
- 项目级 `.kimi-code/mcp.json` 当前选择 `volcengine-coding`。
- 因此本地直接启动和 Kimi 启动不是同一个 Provider。

建议选择一个应用配置作为实际入口，并在该文件中显式声明 `PROVIDER`、对应的专用
凭证变量、`PROXY` 和需要的 `MCP_*` 参数。不要依赖多个来源隐式合并。

### 凭证暴露

以下忽略文件中存在明文 API Key 或含 Key 的命令规则：

- `.env`
- `.kimi-code/mcp.json`
- `.claude/settings.local.json`

这些文件没有被 Git 跟踪，但本地备份、同步工具和权限规则仍可能读取它们。建议吊销并
重新生成已经写入这些文件的凭证；之后不要把 Key 写入 Claude 权限命令模式。

### 配置一致性

README、`.env.example` 与 Provider profile 已统一使用当前端点、模型和上下文默认值。
未列入本说明凭证表的变量不会参与凭证解析。

## 9. 构建和测试配置

- Python：`>=3.12,<3.14`，本地默认 3.12。
- 入口命令：`coding-bridge-mcp`。
- 依赖锁定：`uv.lock`，CI 使用 `uv lock --locked` 和 `uv sync --frozen`。
- CI：Python 3.12/3.13，执行 ruff 和 pytest。
- 默认 pytest 会排除需要真实 API 的 live 测试。

本次检查运行结果：`118 passed, 4 deselected, 3 warnings`。

## 10. 相关实现位置

- Provider profile 和 Provider 选择：[providers.py](/Volumes/Workarea/usr/htdocs/coding-bridge-mcp/src/coding_bridge_mcp/providers.py)
- 环境变量解析和代理校验：[config.py](/Volumes/Workarea/usr/htdocs/coding-bridge-mcp/src/coding_bridge_mcp/config.py)
- `.env` 加载、懒加载和工具参数：[server.py](/Volumes/Workarea/usr/htdocs/coding-bridge-mcp/src/coding_bridge_mcp/server.py)
- httpx、Bearer 鉴权和请求超时：[api_client.py](/Volumes/Workarea/usr/htdocs/coding-bridge-mcp/src/coding_bridge_mcp/api_client.py)
- JSON 日志和 `LOG_LEVEL`：[logging_config.py](/Volumes/Workarea/usr/htdocs/coding-bridge-mcp/src/coding_bridge_mcp/logging_config.py)
