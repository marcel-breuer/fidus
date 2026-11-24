"""Append-only audit trail for user and agent actions."""

from datetime import datetime

from sqlalchemy import select, text
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


async def list_instance_entries(
    session: AsyncSession,
    admin_user: User,
    *,
    before_created_at: datetime | None = None,
    before_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    """List instance audit metadata through the admin-checked database boundary."""
    if not admin_user.is_superuser or not admin_user.is_active:
        raise PermissionError("ADMIN_REQUIRED")
    result = await session.execute(
        text("SELECT * FROM admin_list_audit_entries(:before_created_at, :before_id, :row_limit)"),
        {"before_created_at": before_created_at, "before_id": before_id, "row_limit": limit},
    )
    return [dict(row) for row in result.mappings()]
