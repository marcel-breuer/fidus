"""Operations for revoking and cleaning up authentication sessions."""

from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Session


async def revoke_all_sessions(session: AsyncSession, user_id: str) -> int:
    result = await session.execute(delete(Session).where(Session.user_id == user_id))
    return result.rowcount or 0


async def purge_expired_sessions(session: AsyncSession, now: datetime | None = None) -> int:
    result = await session.execute(
        delete(Session).where(Session.expires_at <= (now or datetime.now(UTC)))
    )
    return result.rowcount or 0
