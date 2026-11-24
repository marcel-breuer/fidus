"""Administrative user management. Every change is audited in the admin's transaction."""

from datetime import datetime

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.services import audit
from app.services.sessions import revoke_all_sessions

# Serializes role and activation changes so two admins cannot each remove the other
# and leave the instance without an active admin.
_ADMIN_CHANGE_LOCK = 727_002


class UserNotFoundError(LookupError):
    """Raised when the target user does not exist."""


class SelfLockoutError(ValueError):
    """Raised when an admin tries to deactivate or demote their own account."""


class LastAdminError(ValueError):
    """Raised when a change would leave the instance without an active admin."""


def _require_admin(admin: User) -> None:
    if not admin.is_superuser:
        raise PermissionError("ADMIN_REQUIRED")


async def list_users(
    session: AsyncSession,
    admin: User,
    *,
    query: str = "",
    before_created_at: datetime | None = None,
    before_id: str | None = None,
    limit: int = 50,
) -> list[User]:
    _require_admin(admin)
    statement = select(User)
    if query:
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(User.email.ilike(f"%{escaped_query}%", escape="\\"))
    if before_created_at is not None and before_id is not None:
        statement = statement.where(
            or_(User.created_at > before_created_at,
                (User.created_at == before_created_at) & (User.id > before_id))
        )
    statement = statement.order_by(User.created_at, User.id).limit(limit + 1)
    return list((await session.scalars(statement)).all())


async def update_user(
    session: AsyncSession,
    admin: User,
    user_id: str,
    *,
    is_active: bool | None = None,
    is_admin: bool | None = None,
) -> User:
    _require_admin(admin)
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADMIN_CHANGE_LOCK})
    target = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise UserNotFoundError(user_id)

    deactivates = is_active is False and target.is_active
    demotes = is_admin is False and target.is_superuser
    if target.id == admin.id and (deactivates or demotes):
        raise SelfLockoutError
    if (deactivates or demotes) and target.is_superuser and target.is_active:
        other_admin = await session.scalar(
            select(User.id)
            .where(User.is_superuser.is_(True), User.is_active.is_(True), User.id != target.id)
            .limit(1)
        )
        if other_admin is None:
            raise LastAdminError

    if is_active is not None and is_active != target.is_active:
        target.is_active = is_active
        revoked = 0
        if not is_active:
            # A deactivated account loses access now, not when its session expires.
            revoked = await revoke_all_sessions(session, target.id)
        await audit.record(
            session, admin, "admin.user.activate" if is_active else "admin.user.deactivate",
            "user", target.id, {"sessions_revoked": revoked}, actor="admin",
        )
    if is_admin is not None and is_admin != target.is_superuser:
        target.is_superuser = is_admin
        await audit.record(
            session, admin, "admin.user.role", "user", target.id,
            {"from": "member" if is_admin else "admin", "to": "admin" if is_admin else "member"},
            actor="admin",
        )
    await session.flush()
    return target
