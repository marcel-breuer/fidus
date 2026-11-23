"""HTTP transport of the MCP endpoint: streamable HTTP with JSON responses and no server stream."""

import json

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.ai.deps import get_embedding_provider
from app.ai.providers import EmbeddingProvider
from app.db.session import user_session
from app.mcp.auth import McpPrincipal, current_mcp_principal
from app.mcp.protocol import (
    INVALID_REQUEST,
    PARSE_ERROR,
    SUPPORTED_PROTOCOL_VERSIONS,
    JsonRpcError,
    McpContext,
    handle_message,
)

MAX_BODY_BYTES = 1024 * 1024

router = APIRouter(prefix="/mcp", include_in_schema=False)


class _LazyEmbedder:
    """Resolves the embedding provider on first use so that initialize and tools/list keep
    working when no provider key is configured. Honors dependency overrides used by tests."""

    def __init__(self, request: Request) -> None:
        self._request = request

    async def embed(self, texts: list[str]) -> list[list[float]]:
        factory = self._request.app.dependency_overrides.get(get_embedding_provider, get_embedding_provider)
        provider: EmbeddingProvider = factory()
        return await provider.embed(texts)


def _error(code: int, message: str, status: int) -> JSONResponse:
    return JSONResponse(JsonRpcError(code, message).body(None), status_code=status)


@router.post("")
@router.post("/")
async def post_mcp(request: Request, principal: McpPrincipal = Depends(current_mcp_principal)) -> Response:
    version = request.headers.get("mcp-protocol-version")
    if version is not None and version not in SUPPORTED_PROTOCOL_VERSIONS:
        return _error(INVALID_REQUEST, "Unsupported MCP-Protocol-Version", 400)
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return _error(INVALID_REQUEST, "Request too large", 413)
    try:
        message = json.loads(body)
    except ValueError:
        return _error(PARSE_ERROR, "Parse error", 400)
    if isinstance(message, list):
        return _error(INVALID_REQUEST, "Batch requests are not supported", 400)

    ctx = McpContext(
        principal=principal,
        open_session=lambda: user_session(principal.user.id),
        embedder=_LazyEmbedder(request),
    )
    response = await handle_message(message, ctx)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(response)


@router.get("")
@router.get("/")
@router.delete("")
@router.delete("/")
async def unsupported_method() -> Response:
    # No server-to-client stream and no sessions to terminate.
    return Response(status_code=405, headers={"Allow": "POST"})
