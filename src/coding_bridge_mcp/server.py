"""FastMCP server implementation for iFlytek Spark / Coding Plan review."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict, List

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field

# Load .env if present before reading configuration. Do not override existing env vars.
load_dotenv(override=False)

from coding_bridge_mcp.config import Settings, load_settings, validate_settings
from coding_bridge_mcp.spark_client import SparkApiError, SparkClient, create_client

# Silence noisy HTTP/WebSocket libraries so they don't pollute MCP stdio.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

mcp = FastMCP("Coding Bridge MCP Server")

DEFAULT_SYSTEM_PROMPT = (
    "你是一个专业、简洁的 AI 编程助手。请根据用户的问题给出清晰、准确的回答，"
    "必要时提供可运行的代码示例。保持回答重点突出，避免过度冗长。"
)

CODE_REVIEW_SYSTEM_PROMPT = (
    "你是一名严格的代码审查员。请对下面这段代码进行全面审查，关注：\n"
    "1. 正确性与潜在 Bug\n"
    "2. 性能与复杂度\n"
    "3. 可读性与命名规范\n"
    "4. 安全性（注入、越界、敏感信息泄露等）\n"
    "5. 可维护性与设计模式\n"
    "请用中文输出审查结论，按优先级列出问题，并给出修改建议或示例代码。"
)

PLAN_REVIEW_SYSTEM_PROMPT = (
    "你是一名资深技术负责人。请对下面的项目计划/实施方案进行审查，关注：\n"
    "1. 需求理解是否准确、范围是否清晰\n"
    "2. 技术选型是否合理、依赖与风险是否充分考虑\n"
    "3. 实施步骤是否可执行、里程碑是否明确\n"
    "4. 是否有遗漏的边界情况、回滚方案、测试与监控\n"
    "5. 资源投入与进度是否现实\n"
    "请用中文输出审查结论，列出优点、风险与改进建议。"
)

# Configuration & client initialization (lazy, so we can report errors via tools).
try:
    _settings: Settings | None = load_settings()
except Exception as _config_exc:
    _settings = None
    _config_error: str | None = str(_config_exc)
else:
    _config_error = None

_client: SparkClient | None = None
_client_error: str | None = None
_client_lock = asyncio.Lock()

# In-memory session store: session_id -> list of messages
_sessions: Dict[str, List[Dict[str, str]]] = {}
_sessions_lock = asyncio.Lock()


async def _ensure_client() -> tuple[SparkClient | None, str | None]:
    """Lazy-initialize the Spark client and surface configuration errors."""
    global _client, _client_error

    if _client is not None:
        return _client, None
    if _client_error is not None:
        return None, _client_error
    if _config_error is not None:
        return None, _config_error

    async with _client_lock:
        if _client is not None:
            return _client, None
        try:
            assert _settings is not None
            validate_settings(_settings)
            _client = create_client(_settings)
        except Exception as exc:
            _client_error = f"Spark client configuration error: {exc}"
            return None, _client_error
        return _client, None


def _default_model() -> str:
    if _settings is not None:
        return _settings.default_model
    return "astron-code-latest"


def _validate_cd(cd: Path) -> tuple[bool, str]:
    cwd_path = Path(cd)
    if not cwd_path.exists():
        return False, f"Working directory does not exist: {cwd_path}"
    if not cwd_path.is_dir():
        return False, f"Path is not a directory: {cwd_path}"
    return True, ""


def _trim_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Trim message history to fit context limits while keeping system prompt."""
    if not messages:
        return messages

    max_chars = _settings.max_context_chars if _settings else 96000
    max_msgs = _settings.max_messages if _settings else 40

    system_msgs: List[Dict[str, str]] = []
    rest: List[Dict[str, str]] = messages[:]
    if rest and rest[0].get("role") == "system":
        system_msgs.append(rest.pop(0))

    while len(system_msgs) + len(rest) > max_msgs and rest:
        rest.pop(0)

    total_chars = sum(len(m.get("content", "")) for m in system_msgs + rest)
    while total_chars > max_chars and len(rest) > 1:
        removed = rest.pop(0)
        total_chars -= len(removed.get("content", ""))

    return system_msgs + rest


async def _get_or_create_session(
    session_id: str,
    system_prompt: str,
) -> List[Dict[str, str]]:
    async with _sessions_lock:
        if session_id not in _sessions:
            _sessions[session_id] = [{"role": "system", "content": system_prompt}]
        return _sessions[session_id]


async def _append_message(
    session_id: str,
    role: str,
    content: str,
) -> None:
    async with _sessions_lock:
        messages = _sessions.get(session_id)
        if messages is None:
            return
        messages.append({"role": role, "content": content})
        _sessions[session_id] = _trim_messages(messages)


async def _execute(
    session_id: str,
    user_content: str,
    system_prompt: str,
    model: str,
    temperature: float = 1.0,
    return_all_messages: bool = False,
) -> Dict[str, Any]:
    """Shared helper: manage session, call Spark, format response."""
    client, err = await _ensure_client()
    if client is None or err:
        return {"success": False, "error": err or "Spark client unavailable"}

    messages = await _get_or_create_session(session_id, system_prompt)
    await _append_message(session_id, "user", user_content)

    try:
        content, usage = await client.call(messages, model, temperature)
    except SparkApiError as exc:
        return {
            "success": False,
            "error": str(exc),
            "all_messages": messages if return_all_messages else None,
        }

    await _append_message(session_id, "assistant", content)

    response: Dict[str, Any] = {
        "success": True,
        "SESSION_ID": session_id,
        "agent_messages": content,
    }
    if usage:
        response["usage"] = usage
    if return_all_messages:
        async with _sessions_lock:
            response["all_messages"] = _sessions.get(session_id, [])
    return response


@mcp.tool(
    name="chat",
    description=(
        "与 Coding Plan 服务进行通用多轮对话，"
        "可用于代码审查、计划审查、问题分析等。\n"
        "必选参数：PROMPT（任务指令）、cd（工作目录）。\n"
        "可选参数：SESSION_ID（继续会话）、model（模型版本）、"
        "return_all_messages（返回完整历史）。"
    ),
    meta={"version": "0.1.0"},
)
async def chat(
    PROMPT: Annotated[str, "Instruction for the task to send to the model."],
    cd: Annotated[Path, "Working directory for the chat session."],
    SESSION_ID: Annotated[
        str,
        Field(
            default="",
            description="Resume the specified chat session. Empty string starts a new session.",
        ),
    ] = "",
    model: Annotated[
        str,
        Field(default="", description="Model version. Empty uses provider default model env."),
    ] = "",
    return_all_messages: Annotated[
        bool,
        Field(default=False, description="Return the full message history for debugging."),
    ] = False,
) -> Dict[str, Any]:
    """Execute a generic chat prompt and return the result."""
    ok, err = _validate_cd(cd)
    if not ok:
        return {"success": False, "error": err}
    if not PROMPT.strip():
        return {"success": False, "error": "PROMPT cannot be empty."}

    model = model or _default_model()
    sid = SESSION_ID or str(uuid.uuid4())

    return await _execute(
        session_id=sid,
        user_content=PROMPT,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        model=model,
        return_all_messages=return_all_messages,
    )


@mcp.tool(
    name="review_code",
    description=(
        "对给定代码进行审查，输出风险、Bug、可读性、安全性与改进建议。\n"
        "必选参数：CODE（代码文本）、cd（工作目录）。\n"
        "可选参数：REQUIREMENTS（额外要求/上下文）、SESSION_ID、model、return_all_messages。"
    ),
    meta={"version": "0.1.0"},
)
async def review_code(
    CODE: Annotated[str, "Source code to review."],
    cd: Annotated[Path, "Working directory for the review session."],
    REQUIREMENTS: Annotated[
        str,
        Field(default="", description="Additional context or requirements for the review."),
    ] = "",
    SESSION_ID: Annotated[
        str,
        Field(default="", description="Resume a previous session. Empty starts a new one."),
    ] = "",
    model: Annotated[
        str,
        Field(default="", description="Model version. Empty uses provider default model env."),
    ] = "",
    return_all_messages: Annotated[bool, Field(default=False)] = False,
) -> Dict[str, Any]:
    """Review source code with the configured provider."""
    ok, err = _validate_cd(cd)
    if not ok:
        return {"success": False, "error": err}
    if not CODE.strip():
        return {"success": False, "error": "CODE cannot be empty."}

    model = model or _default_model()
    sid = SESSION_ID or str(uuid.uuid4())
    user_content = CODE
    if REQUIREMENTS.strip():
        user_content = f"【审查要求/上下文】\n{REQUIREMENTS}\n\n【代码】\n{CODE}"

    return await _execute(
        session_id=sid,
        user_content=user_content,
        system_prompt=CODE_REVIEW_SYSTEM_PROMPT,
        model=model,
        return_all_messages=return_all_messages,
    )


@mcp.tool(
    name="review_plan",
    description=(
        "对项目计划/实施方案进行审查，评估需求、技术选型、风险与可执行性。\n"
        "必选参数：PLAN（计划文本）、cd（工作目录）。\n"
        "可选参数：CONTEXT（项目背景）、SESSION_ID、model、return_all_messages。"
    ),
    meta={"version": "0.1.0"},
)
async def review_plan(
    PLAN: Annotated[str, "Plan or proposal text to review."],
    cd: Annotated[Path, "Working directory for the review session."],
    CONTEXT: Annotated[
        str,
        Field(default="", description="Project background or additional context."),
    ] = "",
    SESSION_ID: Annotated[
        str,
        Field(default="", description="Resume a previous session. Empty starts a new one."),
    ] = "",
    model: Annotated[
        str,
        Field(default="", description="Model version. Empty uses provider default model env."),
    ] = "",
    return_all_messages: Annotated[bool, Field(default=False)] = False,
) -> Dict[str, Any]:
    """Review a project plan with the configured provider."""
    ok, err = _validate_cd(cd)
    if not ok:
        return {"success": False, "error": err}
    if not PLAN.strip():
        return {"success": False, "error": "PLAN cannot be empty."}

    model = model or _default_model()
    sid = SESSION_ID or str(uuid.uuid4())
    user_content = PLAN
    if CONTEXT.strip():
        user_content = f"【项目背景】\n{CONTEXT}\n\n【计划】\n{PLAN}"

    return await _execute(
        session_id=sid,
        user_content=user_content,
        system_prompt=PLAN_REVIEW_SYSTEM_PROMPT,
        model=model,
        return_all_messages=return_all_messages,
    )


def run() -> None:
    """Start the MCP server over stdio transport."""
    mcp.run(transport="stdio")
