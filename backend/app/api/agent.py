"""Memories, agent policy, pending agent actions and the audit trail (chat module)."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_user_scoped_session
from app.auth.manager import current_active_user
from app.db.models import AgentAction, AuditLog, Memory, User
from app.modules.guard import require_module
from app.services import agent_actions, agent_settings, audit, conversations, memories

router = APIRouter(tags=["agent"], dependencies=[Depends(require_module("chat"))])


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=memories.MAX_CONTENT_LENGTH)


class MemoryOut(BaseModel):
    id: str
    content: str
    source: Literal["user", "agent"]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, item: Memory) -> "MemoryOut":
        return cls(
            id=item.id, content=item.content, source=item.source,  # type: ignore[arg-type]
            created_at=item.created_at, updated_at=item.updated_at,
        )


class AgentSettingsOut(BaseModel):
    write_mode: Literal["ask", "allow"]


class AgentActionOut(BaseModel):
    id: str
    conversation_id: str
    message_id: str | None
    tool: str
    arguments: dict
    status: Literal["pending", "approved", "rejected", "failed"]
    created_at: datetime
    decided_at: datetime | None

    @classmethod
    def from_model(cls, item: AgentAction) -> "AgentActionOut":
        return cls(
            id=item.id, conversation_id=item.conversation_id, message_id=item.message_id, tool=item.tool,
            arguments=item.arguments, status=item.status,  # type: ignore[arg-type]
            created_at=item.created_at, decided_at=item.decided_at,
        )


class AuditEntryOut(BaseModel):
    id: str
    actor: str
    action: str
    target_type: str
    target_id: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, item: AuditLog) -> "AuditEntryOut":
        return cls(
            id=item.id, actor=item.actor, action=item.action, target_type=item.target_type,
            target_id=item.target_id, created_at=item.created_at,
        )


@router.get("/memories", response_model=list[MemoryOut])
async def get_memories(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[MemoryOut]:
    return [MemoryOut.from_model(item) for item in await memories.list_memories(session, user)]


@router.post("/memories", response_model=MemoryOut, status_code=201)
async def post_memory(
    body: MemoryIn,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> MemoryOut:
    try:
        return MemoryOut.from_model(await memories.create_memory(session, user, body.content))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="INVALID_MEMORY") from exc
    except memories.MemoryLimitReached as exc:
        raise HTTPException(status_code=409, detail="MEMORY_LIMIT_REACHED") from exc


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
async def patch_memory(
    memory_id: str,
    body: MemoryIn,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> MemoryOut:
    try:
        item = await memories.update_memory(session, user, memory_id, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="INVALID_MEMORY") from exc
    if item is None:
        raise HTTPException(status_code=404, detail="MEMORY_NOT_FOUND")
    return MemoryOut.from_model(item)


@router.delete("/memories/{memory_id}", status_code=204)
async def remove_memory(
    memory_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> Response:
    if not await memories.delete_memory(session, user, memory_id):
        raise HTTPException(status_code=404, detail="MEMORY_NOT_FOUND")
    return Response(status_code=204)


@router.get("/agent/settings", response_model=AgentSettingsOut)
async def get_agent_settings(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> AgentSettingsOut:
    return AgentSettingsOut(write_mode=await agent_settings.get_write_mode(session, user))


@router.put("/agent/settings", response_model=AgentSettingsOut)
async def put_agent_settings(
    body: AgentSettingsOut,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> AgentSettingsOut:
    return AgentSettingsOut(write_mode=await agent_settings.set_write_mode(session, user, body.write_mode))


@router.get("/conversations/{conversation_id}/actions", response_model=list[AgentActionOut])
async def get_conversation_actions(
    conversation_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[AgentActionOut]:
    if await conversations.get_conversation(session, user, conversation_id) is None:
        raise HTTPException(status_code=404, detail="CONVERSATION_NOT_FOUND")
    return [
        AgentActionOut.from_model(item)
        for item in await agent_actions.list_for_conversation(session, user, conversation_id)
    ]


async def _decide(session: AsyncSession, user: User, action_id: str, approve: bool) -> AgentActionOut:
    try:
        return AgentActionOut.from_model(await agent_actions.decide(session, user, action_id, approve))
    except agent_actions.ActionNotFound as exc:
        raise HTTPException(status_code=404, detail="ACTION_NOT_FOUND") from exc
    except agent_actions.ActionNotPending as exc:
        raise HTTPException(status_code=409, detail="ACTION_NOT_PENDING") from exc


@router.post("/agent/actions/{action_id}/approve", response_model=AgentActionOut)
async def approve_action(
    action_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> AgentActionOut:
    return await _decide(session, user, action_id, True)


@router.post("/agent/actions/{action_id}/reject", response_model=AgentActionOut)
async def reject_action(
    action_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> AgentActionOut:
    return await _decide(session, user, action_id, False)


@router.get("/agent/audit", response_model=list[AuditEntryOut])
async def get_audit_log(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[AuditEntryOut]:
    return [AuditEntryOut.from_model(item) for item in await audit.list_entries(session, user)]
