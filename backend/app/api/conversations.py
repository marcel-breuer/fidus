from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_user_scoped_session
from app.auth.manager import current_active_user
from app.db.models import Conversation, Message, User
from app.modules.guard import require_module
from app.services import conversations as service

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

    @classmethod
    def from_model(cls, item: Message) -> "MessageOut":
        return cls(
            id=item.id, conversation_id=item.conversation_id, role=item.role,
            content=item.content, tool_calls=item.tool_calls, citations=item.citations,
            input_tokens=item.input_tokens, output_tokens=item.output_tokens,
            created_at=item.created_at,
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
) -> Response:
    if not await service.delete_conversation(session, user, conversation_id):
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
