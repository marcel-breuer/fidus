"""Minimal MCP (streamable HTTP, JSON responses only) JSON-RPC dispatcher.

The server is stateless: no sessions or server-initiated messages."""

import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import EmbeddingProvider
from app.mcp.auth import McpPrincipal
from app.mcp.tools import TOOLS, TOOLS_BY_NAME, Tool, ToolContext, ToolError
from app.services import audio, files, usage
from app.services.module_settings import enabled_module_keys
from app.storage.base import Storage

LATEST_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = (LATEST_PROTOCOL_VERSION, "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "fidus", "title": "Fidus"}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INSUFFICIENT_SCOPE = -32001
MODULE_DISABLED = -32002
RESOURCE_UNAVAILABLE = -32003
RESOURCE_NOT_FOUND = -32004


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
    storage: Storage


def _tool_allowed(tool: Tool, principal: McpPrincipal) -> bool:
    return tool.scope in principal.scopes


async def _initialize(params: dict[str, Any], ctx: McpContext) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False}},
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
                    session=session, user=ctx.principal.user, embedder=ctx.embedder,
                    storage=ctx.storage, token_id=ctx.principal.token_id
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


async def _resources_list(params: dict[str, Any], ctx: McpContext) -> dict[str, Any]:
    async with ctx.open_session() as session:
        enabled = await enabled_module_keys(session)
        resources: list[dict[str, Any]] = []
        if "files:read" in ctx.principal.scopes and "files" in enabled:
            for node in await files.list_all_files(session, ctx.principal.user):
                resources.append({
                    "uri": f"fidus://files/{node.id}",
                    "name": node.name,
                    "mimeType": "text/plain",
                    "description": "User file content",
                })
        if "audio:read" in ctx.principal.scopes and "audio" in enabled:
            for memo, _document in await audio.list_memos(session, ctx.principal.user):
                resources.append({
                    "uri": f"fidus://memos/{memo.id}",
                    "name": memo.title,
                    "mimeType": "text/plain",
                    "description": "Voice memo transcript",
                })
    return {"resources": resources}


async def _resources_read(params: dict[str, Any], ctx: McpContext) -> dict[str, Any]:
    uri = params.get("uri")
    if not isinstance(uri, str):
        raise JsonRpcError(INVALID_PARAMS, "INVALID_URI")
    parsed = urlsplit(uri)
    if parsed.scheme != "fidus" or parsed.query or parsed.fragment:
        raise JsonRpcError(INVALID_PARAMS, "INVALID_URI")
    resource_id = parsed.path.removeprefix("/")
    if not resource_id or "/" in resource_id or not parsed.netloc:
        raise JsonRpcError(INVALID_PARAMS, "INVALID_URI")
    if parsed.netloc == "files":
        required_scope, module = "files:read", "files"
    elif parsed.netloc == "memos":
        required_scope, module = "audio:read", "audio"
    else:
        raise JsonRpcError(INVALID_PARAMS, "INVALID_URI")
    if required_scope not in ctx.principal.scopes:
        raise JsonRpcError(INSUFFICIENT_SCOPE, "INSUFFICIENT_SCOPE", {"required_scope": required_scope})
    async with ctx.open_session() as session:
        if module not in await enabled_module_keys(session):
            raise JsonRpcError(MODULE_DISABLED, "MODULE_DISABLED", {"module": module})
        if module == "files":
            try:
                found = await files.read_text_content(session, ctx.storage, ctx.principal.user, resource_id)
            except files.FilesError as exc:
                raise JsonRpcError(RESOURCE_UNAVAILABLE, exc.code) from exc
            if found is None:
                raise JsonRpcError(RESOURCE_NOT_FOUND, "RESOURCE_NOT_FOUND")
            content = found[1]
        else:
            found = await audio.get_memo(session, ctx.principal.user, resource_id)
            if found is None:
                raise JsonRpcError(RESOURCE_NOT_FOUND, "RESOURCE_NOT_FOUND")
            memo, document = found
            if document is None or document.content is None:
                raise JsonRpcError(RESOURCE_UNAVAILABLE, "TRANSCRIPT_NOT_READY")
            content = document.content
    return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": content}]}


_METHODS = {
    "initialize": _initialize,
    "ping": _ping,
    "tools/list": _tools_list,
    "tools/call": _tools_call,
    "resources/list": _resources_list,
    "resources/read": _resources_read,
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
