import json
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.deps import (
    get_chat_provider,
    get_embedding_provider,
    get_speech_provider,
    get_transcription_provider,
    get_web_search_provider,
)
from app.ai.providers import ChatProvider, EmbeddingProvider, SpeechProvider, TranscriptionProvider, WebSearchProvider
from app.api.deps import get_user_scoped_session
from app.auth.manager import current_active_user
from app.auth.rate_limit import enforce_user_rate_limit
from app.db.models import Conversation, Message, MessageAttachment, User
from app.modules.guard import require_module
from app.services import chat as chat_service
from app.services import chat_attachments, chat_audio
from app.services import conversations as service
from app.storage.base import Storage
from app.storage.deps import get_storage

router = APIRouter(
    tags=["conversations"],
    dependencies=[Depends(require_module("chat"))],
)


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, item: Conversation) -> "ConversationOut":
        return cls(id=item.id, title=item.title, created_at=item.created_at, updated_at=item.updated_at)


class AttachmentOut(BaseModel):
    id: str
    filename: str
    mime_type: str
    size_bytes: int

    @classmethod
    def from_model(cls, item: MessageAttachment) -> "AttachmentOut":
        return cls(id=item.id, filename=item.filename, mime_type=item.mime_type, size_bytes=item.size_bytes)


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    tool_calls: dict | list | None
    citations: dict | list | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime
    attachments: list[AttachmentOut] = Field(default_factory=list)

    @classmethod
    def from_model(cls, item: Message) -> "MessageOut":
        return cls(
            id=item.id, conversation_id=item.conversation_id, role=item.role,
            content=item.content, tool_calls=item.tool_calls, citations=item.citations,
            input_tokens=item.input_tokens, output_tokens=item.output_tokens,
            created_at=item.created_at,
            attachments=[AttachmentOut.from_model(attachment) for attachment in item.attachments],
        )


class ConversationPage(BaseModel):
    items: list[ConversationOut]
    next_cursor: str | None


class MessagePage(BaseModel):
    items: list[MessageOut]
    next_cursor: str | None


class SearchResult(BaseModel):
    conversation_id: str
    message_id: str
    snippet: str


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=chat_attachments.MAX_ATTACHMENTS_PER_MESSAGE)


class DictationOut(BaseModel):
    text: str


def _sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


async def _chat_events(
    initial: chat_service.ChatStreamEvent,
    events: AsyncIterator[chat_service.ChatStreamEvent],
) -> AsyncIterator[str]:
    try:
        current: chat_service.ChatStreamEvent | None = initial
        while current is not None:
            if isinstance(current, chat_service.ContextReady):
                pass
            elif isinstance(current, chat_service.UserMessageStored):
                yield _sse("message", {
                    "id": current.id,
                    "conversation_id": current.conversation_id,
                    "role": "user",
                    "content": current.content,
                    "created_at": current.created_at.isoformat(),
                    "tool_calls": None,
                    "citations": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "attachments": current.attachments,
                })
            elif isinstance(current, chat_service.Delta):
                yield _sse("delta", {"text": current.text})
            elif isinstance(current, chat_service.ToolStatus):
                yield _sse("tool", {"name": current.name, "status": current.status})
            elif isinstance(current, chat_service.SourcesFound):
                yield _sse("citations", {"items": current.items})
            elif isinstance(current, chat_service.ActionProposed):
                yield _sse("action", {
                    "id": current.id, "tool": current.tool,
                    "arguments": current.arguments, "status": current.status,
                })
            elif isinstance(current, chat_service.Done):
                yield _sse("done", {"message_id": current.message_id, "title": current.title})
            else:
                yield _sse("error", {"code": current.code})
                return
            try:
                current = await events.__anext__()
            except StopAsyncIteration:
                current = None
    finally:
        await events.aclose()


@router.post(
    "/conversations/{conversation_id}/messages/stream",
    responses={429: {"description": "Per-user chat request limit exceeded"}},
    dependencies=[Depends(enforce_user_rate_limit("chat"))],
)
async def stream_message(
    conversation_id: str,
    body: ChatMessageCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    provider: ChatProvider = Depends(get_chat_provider),
    embedder: EmbeddingProvider = Depends(get_embedding_provider),
    web_search: WebSearchProvider | None = Depends(get_web_search_provider),
    storage: Storage = Depends(get_storage),
) -> StreamingResponse:
    try:
        await chat_attachments.validate_ids(session, user, conversation_id, body.attachment_ids)
    except chat_attachments.AttachmentError as exc:
        status = 404 if exc.code == "ATTACHMENT_NOT_FOUND" else 422
        raise HTTPException(status_code=status, detail=exc.code) from exc
    events = chat_service.run_chat_turn(
        user, conversation_id, body.content, provider, embedder=embedder, web_search=web_search, storage=storage,
        attachment_ids=body.attachment_ids,
    )
    try:
        initial = await events.__anext__()
    except chat_service.NotFound as exc:
        await events.aclose()
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND") from exc
    return StreamingResponse(
        _chat_events(initial, events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/conversations/{conversation_id}/dictation",
    response_model=DictationOut,
    responses={429: {"description": "Per-user transcription limit exceeded"}},
    dependencies=[Depends(enforce_user_rate_limit("transcription"))],
)
async def transcribe_dictation(
    conversation_id: str,
    file: UploadFile = File(...),
    language: str | None = None,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    provider: TranscriptionProvider = Depends(get_transcription_provider),
) -> DictationOut:
    if not await chat_audio.ensure_conversation_access(session, user, conversation_id):
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND")
    data = await file.read(chat_audio.MAX_DICTATION_BYTES + 1)
    try:
        text = await chat_audio.transcribe_dictation(user.id, data, file.filename or "", provider, language)
        return DictationOut(text=text)
    except chat_audio.ChatAudioError as exc:
        status = {
            "UNSUPPORTED_TYPE": 415, "FILE_TOO_LARGE": 413, "CLIP_TOO_LONG": 413,
            "EMPTY_FILE": 422, "EMPTY_TRANSCRIPT": 422, "INVALID_LANGUAGE": 422,
            "CORRUPT_AUDIO": 422, "FFMPEG_UNAVAILABLE": 503,
            "TRANSCRIPTION_FAILED": 502, "AUDIO_PROCESSING_FAILED": 422,
        }.get(exc.code, 422)
        raise HTTPException(status_code=status, detail=exc.code) from exc
    finally:
        await file.close()


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/speech",
    responses={
        200: {"content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}},
        429: {"description": "Per-user chat request limit exceeded"},
    },
    dependencies=[Depends(enforce_user_rate_limit("chat"))],
)
async def post_message_speech(
    conversation_id: str,
    message_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    storage: Storage = Depends(get_storage),
    speech: SpeechProvider = Depends(get_speech_provider),
) -> Response:
    try:
        download = await chat_audio.get_message_speech(
            session, storage, user, conversation_id, message_id, speech
        )
    except chat_audio.ChatAudioError as exc:
        status = {"TEXT_TOO_LONG": 413, "NO_MESSAGE_CONTENT": 409, "SPEECH_FAILED": 502}.get(exc.code, 400)
        raise HTTPException(status_code=status, detail=exc.code) from exc
    if download is None:
        raise HTTPException(status_code=404, detail="MESSAGE_NOT_FOUND")
    body = b"".join([block async for block in download.stream])
    return Response(content=body, media_type="audio/wav", headers={"X-Content-Type-Options": "nosniff"})


@router.post(
    "/conversations/{conversation_id}/actions/{action_id}/continue",
    dependencies=[Depends(enforce_user_rate_limit("chat"))],
)
async def continue_after_action(
    conversation_id: str,
    action_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    provider: ChatProvider = Depends(get_chat_provider),
    embedder: EmbeddingProvider = Depends(get_embedding_provider),
    web_search: WebSearchProvider | None = Depends(get_web_search_provider),
    storage: Storage = Depends(get_storage),
) -> StreamingResponse:
    from app.services import agent_actions

    try:
        notice = await agent_actions.outcome_context(session, user, conversation_id, action_id)
    except agent_actions.ActionNotFound as exc:
        raise HTTPException(status_code=404, detail="ACTION_NOT_FOUND") from exc
    except agent_actions.ActionNotPending as exc:
        raise HTTPException(status_code=409, detail="ACTION_NOT_PENDING") from exc
    events = chat_service.run_chat_turn(
        user, conversation_id, "", provider, embedder=embedder, web_search=web_search,
        storage=storage, decision_notice=notice,
    )
    try:
        initial = await events.__anext__()
    except chat_service.NotFound as exc:
        await events.aclose()
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND") from exc
    return StreamingResponse(
        _chat_events(initial, events), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/conversations/{conversation_id}/attachments",
    response_model=AttachmentOut,
    status_code=201,
    dependencies=[Depends(enforce_user_rate_limit("file_upload"))],
)
async def upload_attachment(
    conversation_id: str,
    file: UploadFile = File(...),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    storage: Storage = Depends(get_storage),
) -> AttachmentOut:
    filename = file.filename or ""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mime_type = {
        "pdf": "application/pdf", "txt": "text/plain", "md": "text/markdown", "markdown": "text/markdown",
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
    }.get(suffix)
    if mime_type is None:
        raise HTTPException(status_code=415, detail="UNSUPPORTED_TYPE")
    content = await file.read(chat_attachments.MAX_ATTACHMENT_BYTES + 1)
    try:
        item = await chat_attachments.upload(session, storage, user, conversation_id, filename, mime_type, content)
    except chat_attachments.AttachmentError as exc:
        status = 404 if exc.code == "CONVERSATION_NOT_FOUND" else 413 if exc.code == "FILE_TOO_LARGE" else 422
        raise HTTPException(status_code=status, detail=exc.code) from exc
    return AttachmentOut(id=item.id, filename=item.filename, mime_type=item.mime_type, size_bytes=item.size_bytes)


def _invalid_value(exc: ValueError) -> HTTPException:
    code = "INVALID_CURSOR" if "cursor" in str(exc).lower() else "INVALID_LIMIT"
    return HTTPException(status_code=422, detail=code)


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def post_conversation(
    body: ConversationCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> ConversationOut:
    return ConversationOut.from_model(await service.create_conversation(session, user, body.title))


@router.get("/conversations", response_model=ConversationPage)
async def get_conversations(
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> ConversationPage:
    try:
        items, next_cursor = await service.list_conversations(session, user, cursor, limit)
    except ValueError as exc:
        raise _invalid_value(exc) from exc
    return ConversationPage(items=[ConversationOut.from_model(item) for item in items], next_cursor=next_cursor)


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> ConversationOut:
    item = await service.get_conversation(session, user, conversation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND")
    return ConversationOut.from_model(item)


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
async def patch_conversation(
    conversation_id: str,
    body: ConversationRename,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> ConversationOut:
    item = await service.rename_conversation(session, user, conversation_id, body.title)
    if item is None:
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND")
    return ConversationOut.from_model(item)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def remove_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
    storage: Storage = Depends(get_storage),
) -> Response:
    if not await service.delete_conversation(session, user, conversation_id, storage):
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND")
    return Response(status_code=204)


@router.get("/conversations/{conversation_id}/messages", response_model=MessagePage)
async def get_messages(
    conversation_id: str,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> MessagePage:
    if await service.get_conversation(session, user, conversation_id) is None:
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND")
    try:
        items, next_cursor = await service.list_messages(session, user, conversation_id, cursor, limit)
    except ValueError as exc:
        raise _invalid_value(exc) from exc
    return MessagePage(items=[MessageOut.from_model(item) for item in items], next_cursor=next_cursor)


@router.get("/search/messages", response_model=list[SearchResult])
async def get_search_messages(
    q: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[SearchResult]:
    return [SearchResult(**item) for item in await service.search_messages(session, user, q, limit)]
