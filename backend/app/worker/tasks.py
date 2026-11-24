import json
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import func, select, text

from app.ai.deps import get_embedding_provider
from app.ai.providers import EmbeddingProvider
from app.config import get_settings
from app.db.models import Memo, Task, User
from app.db.session import get_sessionmaker, system_session, user_session
from app.services.audio import enqueue_memo
from app.services.indexing import index_document, mark_document_failed
from app.services.reminders import materialize_due_reminders
from app.services.sessions import purge_expired_sessions
from app.storage.base import Storage
from app.storage.deps import build_storage
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


@broker.task(task_name="files.index_document")
async def index_document_job(user_id: str, document_id: str) -> None:
    await process_index_document(user_id, document_id)


async def process_index_document(
    user_id: str,
    document_id: str,
    storage: Storage | None = None,
    embedder: EmbeddingProvider | None = None,
) -> None:
    from app.worker.module_guard import ensure_module_enabled

    try:
        await ensure_module_enabled("files")
    except RuntimeError as exc:
        if str(exc) != "MODULE_DISABLED":
            raise
        return
    try:
        embedder = embedder or get_embedding_provider()
    except HTTPException as exc:
        if exc.status_code == 503:
            await mark_document_failed(user_id, document_id, "AI_NOT_CONFIGURED")
            return
        raise
    await index_document(user_id, document_id, storage or build_storage(), embedder)


@broker.task(task_name="audio.transcribe_memo")
async def transcribe_memo_job(user_id: str, memo_id: str) -> None:
    from app.services.transcription import process_memo_job

    await process_memo_job(user_id, memo_id)


@broker.task(task_name="sessions.purge_expired", schedule=[{"cron": "15 3 * * *"}])
async def purge_expired_auth_sessions() -> int:
    """Remove expired sessions once per day at 03:15 UTC."""
    async with get_sessionmaker()() as session, session.begin():
        return await purge_expired_sessions(session)


async def recover_stuck_memos(now: datetime, timeout_seconds: int) -> int:
    """Return stale transcription claims to pending and enqueue them once."""
    from app.worker.module_guard import ensure_module_enabled

    try:
        await ensure_module_enabled("audio")
    except RuntimeError as exc:
        if str(exc) == "MODULE_DISABLED":
            return 0
        raise

    async with system_session() as session:
        user_ids = list(await session.scalars(select(User.id)))
    cutoff = now - timedelta(seconds=timeout_seconds)
    recovered: list[tuple[str, str]] = []
    for user_id in user_ids:
        async with user_session(user_id) as session:
            memos = list(
                await session.scalars(
                    select(Memo)
                    .where(
                        Memo.status.in_(("pending", "transcribing")),
                        Memo.updated_at < cutoff,
                    )
                    .order_by(Memo.updated_at, Memo.id)
                    .with_for_update(skip_locked=True)
                )
            )
            for memo in memos:
                if memo.status == "transcribing":
                    memo.status = "pending"
                    memo.error_code = None
                # Restart the timeout so a memo is requeued at most once per timeout window.
                memo.updated_at = now
                recovered.append((user_id, memo.id))
    for user_id, memo_id in recovered:
        await enqueue_memo(user_id, memo_id)
    return len(recovered)


@broker.task(task_name="audio.recover_stuck_memos", schedule=[{"cron": "*/5 * * * *"}])
async def recover_stuck_memo_jobs() -> int:
    settings = get_settings()
    return await recover_stuck_memos(datetime.now(UTC), settings.memo_transcription_timeout_seconds)


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
