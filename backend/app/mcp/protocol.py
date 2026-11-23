"""Minimal MCP (streamable HTTP, JSON responses only) JSON-RPC dispatcher.

The server is stateless: no sessions, no server-initiated messages, tools only."""

import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import EmbeddingProvider
from app.mcp.auth import McpPrincipal
from app.mcp.tools import TOOLS, TOOLS_BY_NAME, Tool, ToolContext, ToolError
from app.services import usage
from app.services.module_settings import enabled_module_keys

LATEST_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = (LATEST_PROTOCOL_VERSION, "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "fidus", "title": "Fidus"}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INSUFFICIENT_SCOPE = -32001
MODULE_DISABLED = -32002


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def body(self, request_id: Any) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}


@dataclass(frozen=True)
class McpContext:
    principal: McpPrincipal
    open_session: Callable[[], AbstractAsyncContextManager[AsyncSession]]
    embedder: EmbeddingProvider


def _tool_allowed(tool: Tool, principal: McpPrincipal) -> bool:
    return tool.scope in principal.scopes


async def _initialize(params: dict[str, Any], ctx: McpContext) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {**SERVER_INFO, "version": _server_version()},
    }


def _server_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("fidus-backend")
    except PackageNotFoundError:
        return "0"


async def _tools_list(params: dict[str, Any], ctx: McpContext) -> dict[str, Any]:
    async with ctx.open_session() as session:
        enabled = await enabled_module_keys(session)
    visible = [t for t in TOOLS if _tool_allowed(t, ctx.principal) and t.module in enabled]
    return {"tools": [tool.descriptor() for tool in visible]}


def _validation_data(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": [str(part) for part in error["loc"]], "msg": error["msg"], "type": error["type"]}
        for error in exc.errors(include_url=False, include_context=False, include_input=False)
    ]


async def _tools_call(params: dict[str, Any], ctx: McpContext) -> dict[str, Any]:
    name = params.get("name")
    tool = TOOLS_BY_NAME.get(name) if isinstance(name, str) else None
    if tool is None:
        raise JsonRpcError(INVALID_PARAMS, "UNKNOWN_TOOL")
    if not _tool_allowed(tool, ctx.principal):
        raise JsonRpcError(INSUFFICIENT_SCOPE, "INSUFFICIENT_SCOPE", {"required_scope": tool.scope})
    await usage.record(ctx.principal.user.id, mcp_calls=1)
    arguments = params.get("arguments") or {}
    try:
        parsed = tool.input_model.model_validate(arguments)
    except ValidationError as exc:
        raise JsonRpcError(INVALID_PARAMS, "INVALID_ARGUMENTS", _validation_data(exc)) from exc
    try:
        async with ctx.open_session() as session:
            if tool.module not in await enabled_module_keys(session):
                raise JsonRpcError(MODULE_DISABLED, "MODULE_DISABLED", {"module": tool.module})
            result = await tool.handler(
                ToolContext(
                    session=session, user=ctx.principal.user, embedder=ctx.embedder, token_id=ctx.principal.token_id
                ), parsed
            )
    except ToolError as exc:
        return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
    return {
        "isError": False,
        "content": [{"type": "text", "text": json.dumps(result, separators=(",", ":"))}],
        "structuredContent": result,
    }


async def _ping(params: dict[str, Any], ctx: McpContext) -> dict[str, Any]:
    return {}


_METHODS = {
    "initialize": _initialize,
    "ping": _ping,
    "tools/list": _tools_list,
    "tools/call": _tools_call,
}


async def handle_message(message: Any, ctx: McpContext) -> dict[str, Any] | None:
    """Return the JSON-RPC response for a request, or None for notifications and client responses."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return JsonRpcError(INVALID_REQUEST, "Invalid Request").body(None)
    method = message.get("method")
    request_id = message.get("id")
    if method is None:
        # A response to a server-initiated request; the server never sends any, so ignore it.
        return None
    if not isinstance(method, str) or isinstance(request_id, bool) or (
        "id" in message and not isinstance(request_id, str | int)
    ):
        return JsonRpcError(INVALID_REQUEST, "Invalid Request").body(None)
    if "id" not in message:
        return None  # Notification, e.g. notifications/initialized.
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return JsonRpcError(INVALID_PARAMS, "Invalid params").body(request_id)
    handler = _METHODS.get(method)
    if handler is None:
        return JsonRpcError(METHOD_NOT_FOUND, "Method not found").body(request_id)
    try:
        return {"jsonrpc": "2.0", "id": request_id, "result": await handler(params, ctx)}
    except JsonRpcError as exc:
        return exc.body(request_id)
