"""User-scoped task operations."""

import base64
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Reminder, Task, User


def _cursor_value(cursor: str | None) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    try:
        created, task_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
        return datetime.fromisoformat(created), task_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("INVALID_CURSOR") from exc


def encode_task_cursor(task: Task) -> str:
    value = f"{task.created_at.isoformat()}|{task.id}".encode()
    return base64.urlsafe_b64encode(value).decode()


async def create_task(
    session: AsyncSession,
    user: User,
    title: str,
    notes: str | None = None,
    due_at: datetime | None = None,
    remind_at: datetime | None = None,
    *,
    now: datetime | None = None,
) -> Task:
    task = Task(user_id=user.id, title=title, notes=notes, due_at=due_at, remind_at=remind_at)
    if now is not None:
        task.created_at = now
        task.updated_at = now
    session.add(task)
    await session.flush()
    await session.refresh(task)
    return task


async def list_tasks(
    session: AsyncSession,
    user: User,
    status: Literal["open", "done", "all"] = "open",
    due_before: datetime | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[Task], str | None]:
    query = select(Task).where(Task.user_id == user.id, Task.deleted_at.is_(None))
    if status == "open":
        query = query.where(Task.done_at.is_(None))
    elif status == "done":
        query = query.where(Task.done_at.is_not(None))
    if due_before is not None:
        query = query.where(Task.due_at <= due_before)
    position = _cursor_value(cursor)
    if position:
        created_at, task_id = position
        query = query.where(tuple_(Task.created_at, Task.id) < tuple_(created_at, task_id))
    rows = list(await session.scalars(query.order_by(Task.created_at.desc(), Task.id.desc()).limit(limit + 1)))
    next_cursor = encode_task_cursor(rows[limit - 1]) if len(rows) > limit else None
    return rows[:limit], next_cursor


async def get_task(session: AsyncSession, user: User, task_id: str) -> Task | None:
    return await session.scalar(
        select(Task).where(Task.id == task_id, Task.user_id == user.id, Task.deleted_at.is_(None))
    )


async def update_task(
    session: AsyncSession, user: User, task_id: str, changes: dict[str, object], *, now: datetime | None = None
) -> Task | None:
    task = await get_task(session, user, task_id)
    if task is None:
        return None
    old_remind_at = task.remind_at
    for field in ("title", "notes", "due_at", "remind_at"):
        if field in changes:
            setattr(task, field, changes[field])
    if task.remind_at != old_remind_at:
        await session.execute(
            Reminder.__table__.update()
            .where(Reminder.task_id == task.id, Reminder.state == "pending")
            .values(state="dismissed", updated_at=now or datetime.now(UTC))
        )
    await session.flush()
    await session.refresh(task)
    return task


async def _set_done(session: AsyncSession, user: User, task_id: str, done: bool, now: datetime) -> Task | None:
    task = await get_task(session, user, task_id)
    if task is None:
        return None
    task.done_at = now if done else None
    if done:
        await session.execute(
            Reminder.__table__.update()
            .where(Reminder.task_id == task.id, Reminder.state == "pending")
            .values(state="dismissed", updated_at=now)
        )
    await session.flush()
    await session.refresh(task)
    return task


async def complete_task(session: AsyncSession, user: User, task_id: str, *, now: datetime | None = None) -> Task | None:
    return await _set_done(session, user, task_id, True, now or datetime.now(UTC))


async def reopen_task(
    session: AsyncSession, user: User, task_id: str, *, now: datetime | None = None
) -> Task | None:
    return await _set_done(session, user, task_id, False, now or datetime.now(UTC))


async def delete_task(session: AsyncSession, user: User, task_id: str, *, now: datetime | None = None) -> bool:
    task = await get_task(session, user, task_id)
    if task is None:
        return False
    deleted_at = now or datetime.now(UTC)
    task.deleted_at = deleted_at
    await session.execute(
        Reminder.__table__.update()
        .where(Reminder.task_id == task.id, Reminder.state == "pending")
        .values(state="dismissed", updated_at=deleted_at)
    )
    await session.flush()
    return True
