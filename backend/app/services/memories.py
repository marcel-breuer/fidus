"""User-owned durable memories: facts the assistant keeps across conversations."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Memory, User
from app.services import audit

MAX_MEMORIES = 200
MAX_CONTENT_LENGTH = 1000
CONTEXT_CHARACTER_BUDGET = 4000


class MemoryLimitReached(Exception):
    """The user already stores the maximum number of memories."""


def _clean(content: str) -> str:
    content = content.strip()
    if not content or len(content) > MAX_CONTENT_LENGTH:
        raise ValueError("Invalid memory content")
    return content


async def create_memory(session: AsyncSession, user: User, content: str, source: str = "user") -> Memory:
    content = _clean(content)
    count = await session.scalar(select(func.count()).select_from(Memory).where(Memory.user_id == user.id))
    if (count or 0) >= MAX_MEMORIES:
        raise MemoryLimitReached
    memory = Memory(user_id=user.id, content=content, source=source)
    session.add(memory)
    await session.flush()
    return memory


async def list_memories(session: AsyncSession, user: User) -> list[Memory]:
    return list((await session.scalars(
        select(Memory).where(Memory.user_id == user.id).order_by(Memory.created_at.desc(), Memory.id.desc())
    )).all())


async def get_memory(session: AsyncSession, user: User, memory_id: str) -> Memory | None:
    return await session.scalar(select(Memory).where(Memory.id == memory_id, Memory.user_id == user.id))


async def update_memory(session: AsyncSession, user: User, memory_id: str, content: str) -> Memory | None:
    content = _clean(content)
    memory = await get_memory(session, user, memory_id)
    if memory is None:
        return None
    memory.content = content
    memory.updated_at = datetime.now(UTC)
    await session.flush()
    await audit.record(session, user, "memory.update", "memory", memory.id, actor="user")
    return memory


async def delete_memory(session: AsyncSession, user: User, memory_id: str) -> bool:
    memory = await get_memory(session, user, memory_id)
    if memory is None:
        return False
    memory_id = memory.id
    await session.delete(memory)
    await session.flush()
    await audit.record(session, user, "memory.delete", "memory", memory_id, actor="user")
    return True


async def memories_for_context(session: AsyncSession, user: User) -> list[str]:
    """Newest memories that fit the context budget."""
    selected: list[str] = []
    used = 0
    for memory in await list_memories(session, user):
        if used + len(memory.content) > CONTEXT_CHARACTER_BUDGET:
            break
        selected.append(memory.content)
        used += len(memory.content)
    return selected
