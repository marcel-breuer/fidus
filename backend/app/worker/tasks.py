from sqlalchemy import func, select

from app.db.models import Task
from app.db.session import get_sessionmaker, user_session
from app.services.sessions import purge_expired_sessions
from app.worker.broker import broker


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
