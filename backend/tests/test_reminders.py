import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.api.tasks import stream_reminders
from app.db.models import Task, User
from app.db.session import get_sessionmaker, set_user_context
from app.services.reminders import dismiss_reminder, list_active_reminders, materialize_due_reminders
from app.services.tasks import complete_task, update_task
from app.worker.tasks import process_due_reminders
from tests.helpers import register


async def _new_user(client, email: str) -> User:
    response = await register(client, email)
    assert response.status_code == 201
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, response.json()["id"])
        user = await session.get(User, response.json()["id"])
        assert user
        return user


async def test_reminder_materialization_filters_due_done_deleted_and_is_idempotent(client) -> None:
    user = await _new_user(client, "reminders@example.com")
    now = datetime(2026, 11, 23, 12, tzinfo=UTC)
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, user.id)
        due = Task(user_id=user.id, title="Due", remind_at=now - timedelta(seconds=1))
        future = Task(user_id=user.id, title="Future", remind_at=now + timedelta(seconds=1))
        done = Task(user_id=user.id, title="Done", remind_at=now, done_at=now)
        deleted = Task(user_id=user.id, title="Deleted", remind_at=now, deleted_at=now)
        session.add_all([due, future, done, deleted])
        await session.flush()
        first = await materialize_due_reminders(session, user, now)
        second = await materialize_due_reminders(session, user, now)
        assert len(first) == 1
        assert second == []
        active = await list_active_reminders(session, user)
        assert [title for _, title in active] == ["Due"]
        assert await dismiss_reminder(session, user, first[0], now=now)
        assert await list_active_reminders(session, user) == []


async def test_reminder_dismiss_is_user_scoped(client) -> None:
    owner = await _new_user(client, "reminder-owner@example.com")
    other = await _new_user(client, "reminder-other@example.com")
    now = datetime(2026, 11, 23, 12, tzinfo=UTC)
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, owner.id)
        task = Task(user_id=owner.id, title="Owned", remind_at=now)
        session.add(task)
        await session.flush()
        reminder_id = (await materialize_due_reminders(session, owner, now))[0]
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, other.id)
        assert not await dismiss_reminder(session, other, reminder_id, now=now)
        assert await list_active_reminders(session, other) == []


async def test_task_changes_dismiss_pending_reminders(client) -> None:
    user = await _new_user(client, "reminder-task-change@example.com")
    now = datetime(2026, 11, 23, 12, tzinfo=UTC)
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, user.id)
        task = Task(user_id=user.id, title="Change reminder", remind_at=now)
        session.add(task)
        await session.flush()
        await materialize_due_reminders(session, user, now)
        await update_task(session, user, task.id, {"remind_at": now + timedelta(hours=1)}, now=now)
        assert await list_active_reminders(session, user) == []
        await complete_task(session, user, task.id, now=now)


class FakeRedis:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.messages.append((channel, message))
        return 1


async def test_worker_only_publishes_for_users_with_due_tasks(client) -> None:
    user = await _new_user(client, "worker-reminder@example.com")
    now = datetime(2026, 11, 23, 12, tzinfo=UTC)
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, user.id)
        session.add(Task(user_id=user.id, title="Due", remind_at=now))
    redis = FakeRedis()
    result = await process_due_reminders(redis, now)
    assert set(result) == {user.id}
    assert len(redis.messages) == 1
    assert redis.messages[0][0] == f"reminders:{user.id}"
    assert user.id not in await process_due_reminders(FakeRedis(), now)


async def test_due_user_function_is_not_publicly_executable(owner_engine) -> None:
    async with owner_engine.connect() as connection:
        public_can_execute = await connection.scalar(
            text(
                """SELECT EXISTS (
                    SELECT 1 FROM pg_proc p, LATERAL aclexplode(
                        coalesce(p.proacl, acldefault('f', p.proowner))
                    ) a WHERE p.proname = 'users_with_due_tasks'
                      AND a.grantee = 0 AND a.privilege_type = 'EXECUTE'
                )"""
            )
        )
        function_returns_ids = await connection.scalar(
            text(
                "SELECT pg_get_function_result(oid) = 'SETOF text' "
                "FROM pg_proc WHERE proname = 'users_with_due_tasks'"
            )
        )
    assert public_can_execute is False
    assert function_returns_ids is True


class FakePubSub:
    def __init__(self) -> None:
        self.unsubscribed = False

    async def subscribe(self, channel: str) -> None:
        assert channel.startswith("reminders:")

    async def get_message(self, *, ignore_subscribe_messages: bool, timeout: int) -> dict[str, str]:
        assert ignore_subscribe_messages and timeout == 20
        return {"type": "message", "data": "{}"}

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed = True

    async def aclose(self) -> None:
        return None


class FakeRedisSubscriber:
    def __init__(self) -> None:
        self.subscription = FakePubSub()

    def pubsub(self) -> FakePubSub:
        return self.subscription


class FakeRequest:
    def __init__(self) -> None:
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > 1


async def test_sse_sends_initial_active_list_then_refresh_and_closes_subscription(client) -> None:
    user = await _new_user(client, "sse-reminder@example.com")
    now = datetime(2026, 11, 23, 12, tzinfo=UTC)
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, user.id)
        session.add(Task(user_id=user.id, title="Streamed", remind_at=now))
        await session.flush()
        await materialize_due_reminders(session, user, now)
    redis = FakeRedisSubscriber()
    response = await stream_reminders(FakeRequest(), user, redis, asyncio.sleep)  # type: ignore[arg-type]
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    chunks = [chunk.decode() if isinstance(chunk, bytes) else chunk async for chunk in response.body_iterator]
    assert len(chunks) == 2
    assert '"task_title": "Streamed"' in chunks[0]
    assert chunks[0].startswith("event: reminders")
    assert chunks[1].startswith("event: reminders")
    assert redis.subscription.unsubscribed
