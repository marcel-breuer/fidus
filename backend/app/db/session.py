from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def set_user_context(session: AsyncSession, user_id: str) -> None:
    """Scope the current transaction to one user.

    set_config(..., true) is the parameterizable form of SET LOCAL: the value is
    dropped at commit or rollback, so it cannot leak to the next pooled use."""
    await session.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": user_id})


@asynccontextmanager
async def user_session(user_id: str) -> AsyncIterator[AsyncSession]:
    """One transaction scoped to user_id. Commits on success, rolls back on error."""
    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, user_id)
        yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """Transaction without user context, for authentication lookups only.
    Row-level-secured tables return no rows here."""
    async with get_sessionmaker()() as session, session.begin():
        yield session
