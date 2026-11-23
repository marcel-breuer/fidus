from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import Task, User
from app.db.session import get_sessionmaker, set_user_context
from app.services.tasks import complete_task, create_task, delete_task, get_task, list_tasks, reopen_task, update_task
from tests.helpers import register


async def _user(client, email: str) -> User:
    created = await register(client, email)
    assert created.status_code == 201
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, created.json()["id"])
        user = await session.get(User, created.json()["id"])
        assert user is not None
        return user


async def test_task_service_scopes_users_and_soft_deletes(client) -> None:
    owner = await _user(client, "owner-tasks@example.com")
    other = await _user(client, "other-tasks@example.com")
    now = datetime(2026, 11, 23, 12, tzinfo=UTC)
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, owner.id)
        task = await create_task(session, owner, "Private task", now=now)
        task_id = task.id
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, other.id)
        assert await get_task(session, other, task_id) is None
        assert (await list_tasks(session, other))[0] == []
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, owner.id)
        assert await delete_task(session, owner, task_id, now=now)
        assert await get_task(session, owner, task_id) is None


async def test_task_service_completion_reopen_and_reminder_change(client) -> None:
    created = await register(client, "task-lifecycle@example.com")
    assert created.status_code == 201
    user_id = created.json()["id"]
    now = datetime(2026, 11, 23, 12, tzinfo=UTC)
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, user_id)
        user = await session.get(User, user_id)
        assert user
        task = await create_task(session, user, "Lifecycle", remind_at=now + timedelta(hours=1))
        task_id = task.id
        assert (await update_task(session, user, task_id, {"remind_at": None}, now=now)).remind_at is None
        assert (await complete_task(session, user, task_id, now=now)).done_at == now
        assert (await reopen_task(session, user, task_id)).done_at is None
        rows = await session.scalars(select(Task).where(Task.id == task_id))
        assert rows.one().deleted_at is None
