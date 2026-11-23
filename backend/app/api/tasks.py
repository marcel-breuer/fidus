"""REST adapters for the tasks module and its in-app reminders."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_user_scoped_session
from app.auth.manager import current_active_user
from app.db.models import Reminder, User
from app.db.session import user_session
from app.modules.guard import require_module
from app.services import reminders, tasks

router = APIRouter(dependencies=[Depends(require_module("tasks"))], tags=["tasks"])


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    notes: str | None = None
    due_at: datetime | None = None
    remind_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title cannot be blank")
        return value


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    notes: str | None = None
    due_at: datetime | None = None
    remind_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def title_cannot_be_null(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            raise ValueError("title cannot be blank")
        return value


class TaskOut(BaseModel):
    id: str
    title: str
    notes: str | None
    due_at: datetime | None
    remind_at: datetime | None
    done_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskPage(BaseModel):
    items: list[TaskOut]
    next_cursor: str | None


class ReminderOut(BaseModel):
    id: str
    task_id: str
    task_title: str
    due_at: datetime
    state: str


async def get_reminder_redis() -> AsyncIterator[Redis]:
    from app.config import get_settings

    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def get_stream_sleep() -> Callable[[float], Awaitable[None]]:
    return asyncio.sleep


def _reminder_rows(rows: list[tuple[Reminder, str]]) -> list[ReminderOut]:
    return [
        ReminderOut(
            id=reminder.id,
            task_id=reminder.task_id,
            task_title=title,
            due_at=reminder.due_at,
            state=reminder.state,
        )
        for reminder, title in rows
    ]


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def post_task(
    body: TaskCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> TaskOut:
    task = await tasks.create_task(session, user, **body.model_dump())
    return TaskOut.model_validate(task, from_attributes=True)


@router.get("/tasks", response_model=TaskPage)
async def get_tasks(
    status: Literal["open", "done", "all"] = Query(default="open"),
    due_before: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> TaskPage:
    try:
        items, next_cursor = await tasks.list_tasks(session, user, status, due_before, cursor, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="INVALID_CURSOR") from exc
    return TaskPage(
        items=[TaskOut.model_validate(item, from_attributes=True) for item in items],
        next_cursor=next_cursor,
    )


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> TaskOut:
    task = await tasks.get_task(session, user, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
    return TaskOut.model_validate(task, from_attributes=True)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def patch_task(
    task_id: str,
    body: TaskUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> TaskOut:
    task = await tasks.update_task(session, user, task_id, body.model_dump(exclude_unset=True))
    if task is None:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
    return TaskOut.model_validate(task, from_attributes=True)


@router.delete("/tasks/{task_id}", status_code=204)
async def remove_task(
    task_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> Response:
    if not await tasks.delete_task(session, user, task_id):
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
    return Response(status_code=204)


@router.post("/tasks/{task_id}/complete", response_model=TaskOut)
async def post_complete(
    task_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> TaskOut:
    task = await tasks.complete_task(session, user, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
    return TaskOut.model_validate(task, from_attributes=True)


@router.post("/tasks/{task_id}/reopen", response_model=TaskOut)
async def post_reopen(
    task_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> TaskOut:
    task = await tasks.reopen_task(session, user, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="TASK_NOT_FOUND")
    return TaskOut.model_validate(task, from_attributes=True)


@router.get("/reminders", response_model=list[ReminderOut])
async def get_reminders(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[ReminderOut]:
    return _reminder_rows(await reminders.list_active_reminders(session, user))


@router.post("/reminders/{reminder_id}/dismiss", status_code=204)
async def post_dismiss_reminder(
    reminder_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> Response:
    if not await reminders.dismiss_reminder(session, user, reminder_id):
        raise HTTPException(status_code=404, detail="REMINDER_NOT_FOUND")
    return Response(status_code=204)


@router.get("/reminders/stream")
async def stream_reminders(
    request: Request,
    user: User = Depends(current_active_user),
    redis: Redis = Depends(get_reminder_redis),
    sleep: Callable[[float], Awaitable[None]] = Depends(get_stream_sleep),
) -> StreamingResponse:
    async def active_payload() -> str:
        async with user_session(user.id) as session:
            rows = await reminders.list_active_reminders(session, user)
        return json.dumps([item.model_dump(mode="json") for item in _reminder_rows(rows)])

    async def events() -> AsyncIterator[str]:
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"reminders:{user.id}")
        try:
            yield f"event: reminders\ndata: {await active_payload()}\n\n"
            while not await request.is_disconnected():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=20)
                if message:
                    yield f"event: reminders\ndata: {await active_payload()}\n\n"
                else:
                    await sleep(0)
                    yield ": keepalive\n\n"
        finally:
            await pubsub.unsubscribe(f"reminders:{user.id}")
            await pubsub.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
