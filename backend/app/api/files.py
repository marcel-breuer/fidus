from collections.abc import AsyncIterator
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.config import get_model_config
from app.ai.deps import get_embedding_provider
from app.ai.providers import EmbeddingProvider
from app.api.deps import get_user_scoped_session
from app.auth.manager import current_active_user
from app.db.models import FileVersion, Node, User
from app.modules.guard import require_module
from app.services import files as service
from app.services.files import FilesError
from app.services.indexing import latest_document, retry_latest_document
from app.services.module_settings import enabled_module_keys
from app.services.retrieval import search_knowledge
from app.storage.base import Storage, StorageTooLarge
from app.storage.deps import get_storage

router = APIRouter(dependencies=[Depends(require_module("files"))], tags=["files"])


class NodeOut(BaseModel):
    id: str
    parent_id: str | None
    kind: str
    name: str
    created_at: datetime
    updated_at: datetime
    size_bytes: int | None = None


class VersionOut(BaseModel):
    id: str
    version: int
    size_bytes: int
    mime_type: str
    created_at: datetime


class FolderCreate(BaseModel):
    name: str
    parent_id: str | None = None


class TextFileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content: str = Field(max_length=service.MAX_UPLOAD_BYTES)
    parent_id: str | None = None


class TextFileUpdate(BaseModel):
    content: str = Field(max_length=service.MAX_UPLOAD_BYTES)


class TextFileOut(NodeOut):
    version: int


class NodeUpdate(BaseModel):
    name: str | None = None
    parent_id: str | None = None


class DocumentStatusOut(BaseModel):
    status: str
    chunk_count: int
    error_code: str | None


class CitationOut(BaseModel):
    chunk_id: str
    document_id: str
    node_id: str | None
    folder_id: str | None
    file_name: str
    version: int | None
    position: int
    snippet: str
    score: float
    source: str = "upload"
    memo_id: str | None = None


class SearchOut(BaseModel):
    results: list[CitationOut]


def _node(node: Node, size: int | None = None) -> NodeOut:
    return NodeOut(
        id=node.id,
        parent_id=node.parent_id,
        kind=node.kind,
        name=node.name,
        created_at=node.created_at,
        updated_at=node.updated_at,
        size_bytes=size,
    )


def _error(exc: FilesError) -> HTTPException:
    status = {
        "INVALID_NAME": 422,
        "UNSUPPORTED_TYPE": 415,
        "PARENT_NOT_FOUND": 404,
        "NODE_NOT_FOUND": 404,
        "NAME_CONFLICT": 409,
        "MOVE_CYCLE": 422,
    }.get(exc.code, 400)
    return HTTPException(status_code=status, detail=exc.code)


@router.get("/files/nodes", response_model=list[NodeOut])
async def get_children(
    parent_id: str | None = None,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[NodeOut]:
    try:
        nodes = await service.list_children(session, user, parent_id)
    except FilesError as exc:
        raise _error(exc) from exc
    output = []
    for node in nodes:
        versions = await service.list_versions(session, user, node.id) if node.kind == "file" else None
        output.append(_node(node, versions[0].size_bytes if versions else None))
    return output


@router.post("/files/folders", response_model=NodeOut, status_code=201)
async def post_folder(
    body: FolderCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> NodeOut:
    try:
        return _node(await service.create_folder(session, user, body.name, body.parent_id))
    except FilesError as exc:
        raise _error(exc) from exc


def _text_file(node: Node, version: FileVersion) -> TextFileOut:
    return TextFileOut(
        id=node.id,
        parent_id=node.parent_id,
        kind=node.kind,
        name=node.name,
        created_at=node.created_at,
        updated_at=node.updated_at,
        size_bytes=version.size_bytes,
        version=version.version,
    )


@router.post("/files/text", response_model=TextFileOut, status_code=201)
async def post_text_file(
    body: TextFileCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    storage: Storage = Depends(get_storage),
) -> TextFileOut:
    try:
        node, version = await service.create_text_file(
            session, storage, user, body.parent_id, body.name, body.content
        )
    except StorageTooLarge as exc:
        raise HTTPException(status_code=413, detail="FILE_TOO_LARGE") from exc
    except FilesError as exc:
        raise _error(exc) from exc
    return _text_file(node, version)


@router.put("/files/nodes/{node_id}/text", response_model=TextFileOut)
async def put_text_file(
    node_id: str,
    body: TextFileUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    storage: Storage = Depends(get_storage),
) -> TextFileOut:
    try:
        node, version = await service.update_text_file(session, storage, user, node_id, body.content)
    except StorageTooLarge as exc:
        raise HTTPException(status_code=413, detail="FILE_TOO_LARGE") from exc
    except FilesError as exc:
        raise _error(exc) from exc
    return _text_file(node, version)


@router.post("/files/upload", response_model=NodeOut, status_code=201)
async def post_upload(
    file: UploadFile = File(...),
    parent_id: str | None = Form(default=None),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    storage: Storage = Depends(get_storage),
) -> NodeOut:
    async def chunks() -> AsyncIterator[bytes]:
        while chunk := await file.read(1024 * 1024):
            yield chunk

    try:
        node, version = await service.upload_file(
            session,
            storage,
            user,
            parent_id,
            file.filename or "",
            chunks(),
            file.content_type,
        )
        return _node(node, version.size_bytes)
    except StorageTooLarge as exc:
        raise HTTPException(status_code=413, detail="FILE_TOO_LARGE") from exc
    except FilesError as exc:
        raise _error(exc) from exc
    finally:
        await file.close()


@router.patch("/files/nodes/{node_id}", response_model=NodeOut)
async def patch_node(
    node_id: str,
    body: NodeUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> NodeOut:
    try:
        node = await service.rename_or_move(
            session,
            user,
            node_id,
            name=body.name,
            parent_id=body.parent_id,
            move_requested="parent_id" in body.model_fields_set,
        )
    except FilesError as exc:
        raise _error(exc) from exc
    if node is None:
        raise HTTPException(status_code=404, detail="NODE_NOT_FOUND")
    return _node(node)


@router.delete("/files/nodes/{node_id}", status_code=204)
async def delete_node(
    node_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> Response:
    if not await service.soft_delete(session, user, node_id):
        raise HTTPException(status_code=404, detail="NODE_NOT_FOUND")
    return Response(status_code=204)


@router.get("/files/nodes/{node_id}/versions", response_model=list[VersionOut])
async def get_versions(
    node_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[VersionOut]:
    rows = await service.list_versions(session, user, node_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="NODE_NOT_FOUND")
    return [VersionOut.model_validate(row, from_attributes=True) for row in rows]


@router.get("/files/nodes/{node_id}/document", response_model=DocumentStatusOut)
async def get_document_status(
    node_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> DocumentStatusOut:
    node = await session.scalar(
        select(Node).where(
            Node.id == node_id, Node.user_id == user.id, Node.kind == "file", Node.deleted_at.is_(None)
        )
    )
    document = await latest_document(session, user, node_id) if node is not None else None
    if document is None:
        raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND")
    return DocumentStatusOut(status=document.status, chunk_count=document.chunk_count, error_code=document.error_code)


@router.post("/files/nodes/{node_id}/reindex", response_model=DocumentStatusOut)
async def post_reindex(
    node_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> DocumentStatusOut:
    document = await retry_latest_document(session, user, node_id)
    if document is None:
        raise HTTPException(status_code=404, detail="DOCUMENT_NOT_FOUND")
    return DocumentStatusOut(status=document.status, chunk_count=document.chunk_count, error_code=document.error_code)


@router.get("/knowledge/search", response_model=SearchOut)
async def get_knowledge_search(
    q: str = Query(min_length=1, max_length=2000),
    limit: int | None = Query(default=None, ge=1, le=20),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    embedder: EmbeddingProvider = Depends(get_embedding_provider),
) -> SearchOut:
    if not q.strip():
        raise HTTPException(status_code=422, detail="QUERY_REQUIRED")
    include_memos = "audio" in await enabled_module_keys(session)
    hits = await search_knowledge(
        session, user, q, embedder, limit or get_model_config().retrieval.top_k, include_memos=include_memos
    )
    return SearchOut(results=[CitationOut.model_validate(hit, from_attributes=True) for hit in hits])


@router.get("/files/nodes/{node_id}/download")
async def download_node(
    node_id: str,
    version: int | None = None,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    storage: Storage = Depends(get_storage),
) -> StreamingResponse:
    download = await service.get_download(session, storage, user, node_id, version)
    if download is None:
        raise HTTPException(status_code=404, detail="NODE_NOT_FOUND")
    row: FileVersion = download.version
    node = await session.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="NODE_NOT_FOUND")
    safe_fallback = "".join(c if c.isascii() and c.isalnum() or c in " ._-" else "_" for c in node.name)
    disposition = f"attachment; filename=\"{safe_fallback}\"; filename*=UTF-8''{quote(node.name, safe='')}"
    return StreamingResponse(
        download.stream,
        media_type=row.mime_type,
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(row.size_bytes),
        },
    )
