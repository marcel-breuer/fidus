import json
from datetime import UTC, datetime
from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db.models import Task, User
from app.db.session import get_sessionmaker, system_session, user_session
from app.services.reminders import materialize_due_reminders
from app.services.sessions import purge_expired_sessions
from app.worker.broker import broker


class RedisPublisher(Protocol):
    async def publish(self, channel: str, message: str) -> int: ...


@broker.task(task_name="tasks.count_open")
async def count_open_tasks(user_id: str) -> int:
    """Example job. Jobs carry the owning user id and run in that user's RLS context."""
    async with user_session(user_id) as session:
        result = await session.scalar(
            select(func.count()).select_from(Task).where(Task.done_at.is_(None))
        )
    return int(result or 0)


@broker.task(task_name="sessions.purge_expired", schedule=[{"cron": "15 3 * * *"}])
async def purge_expired_auth_sessions() -> int:
    """Remove expired sessions once per day at 03:15 UTC."""
    async with get_sessionmaker()() as session, session.begin():
        return await purge_expired_sessions(session)


async def process_due_reminders(redis: RedisPublisher, now: datetime) -> dict[str, list[str]]:
    """Materialize due reminders under owner RLS contexts and publish per-user events."""
    from app.worker.module_guard import ensure_module_enabled

    await ensure_module_enabled("tasks")
    async with system_session() as session:
        users = list(
            await session.scalars(
                text("SELECT users_with_due_tasks(:now)"), {"now": now}
            )
        )
    published: dict[str, list[str]] = {}
    for user_id in users:
        async with user_session(user_id) as session:
            user = await session.get(User, user_id)
            if user is None:
                continue
            reminder_ids = await materialize_due_reminders(session, user, now)
        if reminder_ids:
            await redis.publish(
                f"reminders:{user_id}",
                json.dumps({"reminder_ids": reminder_ids}),
            )
            published[user_id] = reminder_ids
    return published


@broker.task(task_name="reminders.mark_due", schedule=[{"cron": "* * * * *"}])
async def mark_due_reminders() -> None:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        await process_due_reminders(redis, datetime.now(UTC))
    finally:
        await redis.aclose()
