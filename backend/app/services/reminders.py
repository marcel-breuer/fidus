"""Reminder materialization and user-scoped reminder actions."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import new_id
from app.db.models import Reminder, Task, User


async def materialize_due_reminders(session: AsyncSession, user: User, now: datetime) -> list[str]:
    due_tasks = await session.scalars(
        select(Task).where(
            Task.user_id == user.id,
            Task.remind_at <= now,
            Task.done_at.is_(None),
            Task.deleted_at.is_(None),
        )
    )
    ids: list[str] = []
    for task in due_tasks:
        if task.remind_at is None:
            continue
        reminder_id = new_id()
        result = await session.execute(
            insert(Reminder)
            .values(
                id=reminder_id,
                user_id=user.id,
                task_id=task.id,
                due_at=task.remind_at,
                state="pending",
            )
            .on_conflict_do_nothing(constraint="uq_reminders_task_id_due_at")
            .returning(Reminder.id)
        )
        created = result.scalar_one_or_none()
        if created:
            ids.append(created)
    return ids


async def list_active_reminders(session: AsyncSession, user: User) -> list[tuple[Reminder, str]]:
    rows = await session.execute(
        select(Reminder, Task.title)
        .join(Task, Task.id == Reminder.task_id)
        .where(Reminder.user_id == user.id, Reminder.state.in_(("pending", "shown")), Task.deleted_at.is_(None))
        .order_by(Reminder.due_at, Reminder.id)
    )
    return list(rows.all())


async def mark_shown(session: AsyncSession, user: User, reminder_id: str, *, now: datetime | None = None) -> bool:
    result = await session.execute(
        update(Reminder)
        .where(Reminder.id == reminder_id, Reminder.user_id == user.id, Reminder.state == "pending")
        .values(state="shown", updated_at=now or datetime.now(UTC))
    )
    return result.rowcount == 1


async def dismiss_reminder(session: AsyncSession, user: User, reminder_id: str, *, now: datetime | None = None) -> bool:
    result = await session.execute(
        update(Reminder)
        .where(Reminder.id == reminder_id, Reminder.user_id == user.id, Reminder.state.in_(("pending", "shown")))
        .values(state="dismissed", updated_at=now or datetime.now(UTC))
    )
    return result.rowcount == 1
