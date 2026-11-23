from sqlalchemy import func, select

from app.db.models import Task
from app.db.session import user_session
from app.worker.broker import broker


@broker.task(task_name="tasks.count_open")
async def count_open_tasks(user_id: str) -> int:
    """Example job. Jobs carry the owning user id and run in that user's RLS context."""
    async with user_session(user_id) as session:
        result = await session.scalar(
            select(func.count()).select_from(Task).where(Task.done_at.is_(None))
        )
    return int(result or 0)
