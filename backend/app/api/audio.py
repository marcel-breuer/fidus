from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deps import get_speech_provider
from app.ai.providers import SpeechProvider
from app.api.deps import get_user_scoped_session
from app.auth.manager import current_active_user
from app.auth.rate_limit import enforce_user_rate_limit
from app.db.models import Document, Memo, User
from app.modules.guard import require_module
from app.services import audio as service
from app.services.audio import AudioError
from app.storage.base import Storage, StorageTooLarge
from app.storage.deps import get_storage

router = APIRouter(dependencies=[Depends(require_module("audio"))], tags=["audio"])


class MemoOut(BaseModel):
    id: str
    title: str
    status: str
    error_code: str | None
    mime_type: str
    size_bytes: int
    language: str | None
    document_id: str | None
    index_status: str | None
    index_error_code: str | None
    created_at: datetime
    updated_at: datetime


class MemoDetailOut(MemoOut):
    transcript: str | None


class MemoUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


def _out(memo: Memo, document: Document | None) -> MemoOut:
    return MemoOut(
        id=memo.id,
        title=memo.title,
        status=memo.status,
        error_code=memo.error_code,
        mime_type=memo.mime_type,
        size_bytes=memo.size_bytes,
        language=memo.language,
        document_id=memo.document_id,
        index_status=document.status if document is not None else None,
        index_error_code=document.error_code if document is not None else None,
        created_at=memo.created_at,
        updated_at=memo.updated_at,
    )


def _error(exc: AudioError) -> HTTPException:
    status = {
        "UNSUPPORTED_TYPE": 415,
        "EMPTY_FILE": 422,
        "INVALID_LANGUAGE": 422,
        "INVALID_TITLE": 422,
        "NOT_RETRYABLE": 409,
        "NO_TRANSCRIPT": 409,
        "TEXT_TOO_LONG": 413,
        "SPEECH_FAILED": 502,
    }.get(exc.code, 400)
    return HTTPException(status_code=status, detail=exc.code)


@router.get("/audio/memos", response_model=list[MemoOut])
async def get_memos(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[MemoOut]:
    return [_out(memo, document) for memo, document in await service.list_memos(session, user)]


@router.post(
    "/audio/memos",
    response_model=MemoOut,
    status_code=201,
    responses={429: {"description": "Per-user transcription limit exceeded"}},
    dependencies=[Depends(enforce_user_rate_limit("transcription"))],
)
async def post_memo(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    language: str | None = Form(default=None),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    storage: Storage = Depends(get_storage),
) -> MemoOut:
    async def chunks() -> AsyncIterator[bytes]:
        while chunk := await file.read(1024 * 1024):
            yield chunk

    try:
        memo = await service.create_memo(
            session, storage, user, file.filename or "", chunks(), title, language
        )
        return _out(memo, None)
    except StorageTooLarge as exc:
        raise HTTPException(status_code=413, detail="FILE_TOO_LARGE") from exc
    except AudioError as exc:
        raise _error(exc) from exc
    finally:
        await file.close()


@router.get("/audio/memos/{memo_id}", response_model=MemoDetailOut)
async def get_memo(
    memo_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> MemoDetailOut:
    found = await service.get_memo(session, user, memo_id)
    if found is None:
        raise HTTPException(status_code=404, detail="MEMO_NOT_FOUND")
    memo, document = found
    return MemoDetailOut(**_out(memo, document).model_dump(), transcript=document.content if document else None)


@router.patch("/audio/memos/{memo_id}", response_model=MemoOut)
async def patch_memo(
    memo_id: str,
    body: MemoUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> MemoOut:
    try:
        memo = await service.rename_memo(session, user, memo_id, body.title)
    except AudioError as exc:
        raise _error(exc) from exc
    if memo is None:
        raise HTTPException(status_code=404, detail="MEMO_NOT_FOUND")
    found = await service.get_memo(session, user, memo_id)
    assert found is not None
    return _out(*found)


@router.delete("/audio/memos/{memo_id}", status_code=204)
async def delete_memo(
    memo_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    storage: Storage = Depends(get_storage),
) -> Response:
    if not await service.delete_memo(session, storage, user, memo_id):
        raise HTTPException(status_code=404, detail="MEMO_NOT_FOUND")
    return Response(status_code=204)


@router.post("/audio/memos/{memo_id}/retry", response_model=MemoOut)
async def post_retry(
    memo_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> MemoOut:
    try:
        memo = await service.retry_memo(session, user, memo_id)
    except AudioError as exc:
        raise _error(exc) from exc
    if memo is None:
        raise HTTPException(status_code=404, detail="MEMO_NOT_FOUND")
    found = await service.get_memo(session, user, memo_id)
    assert found is not None
    return _out(*found)


@router.get("/audio/memos/{memo_id}/audio")
async def get_memo_audio(
    memo_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    storage: Storage = Depends(get_storage),
) -> StreamingResponse:
    download = await service.get_audio(session, storage, user, memo_id)
    if download is None:
        raise HTTPException(status_code=404, detail="MEMO_NOT_FOUND")
    return StreamingResponse(
        download.stream,
        media_type=download.memo.mime_type,
        headers={"X-Content-Type-Options": "nosniff", "Content-Length": str(download.memo.size_bytes)},
    )


@router.post("/audio/memos/{memo_id}/speech")
async def post_memo_speech(
    memo_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    storage: Storage = Depends(get_storage),
    speech: SpeechProvider = Depends(get_speech_provider),
) -> Response:
    try:
        download = await service.get_speech(session, storage, user, memo_id, speech)
    except AudioError as exc:
        raise _error(exc) from exc
    if download is None:
        raise HTTPException(status_code=404, detail="MEMO_NOT_FOUND")
    body = b"".join([block async for block in download.stream])
    return Response(
        content=body, media_type="audio/wav", headers={"X-Content-Type-Options": "nosniff"}
    )
