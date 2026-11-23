"""Append-only audit trail for writes made by the agent."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, User


async def record(
    session: AsyncSession,
    user: User,
    action: str,
    target_type: str,
    target_id: str | None,
    details: dict | None = None,
    actor: str = "agent",
) -> AuditLog:
    """Write in the caller's transaction so the audit row commits with the change it describes."""
    entry = AuditLog(
        user_id=user.id, actor=actor, action=action, target_type=target_type,
        target_id=target_id, details=details,
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_entries(session: AsyncSession, user: User, limit: int = 50) -> list[AuditLog]:
    return list((await session.scalars(
        select(AuditLog).where(AuditLog.user_id == user.id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit)
    )).all())
