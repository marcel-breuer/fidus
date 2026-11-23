import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Invitation, User
from app.services import audit


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_invitation(
    session: AsyncSession, admin_user: User, ttl: timedelta
) -> tuple[Invitation, str]:
    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        created_by=admin_user.id,
        token_hash=_token_hash(token),
        expires_at=datetime.now(UTC) + ttl,
    )
    session.add(invitation)
    await session.flush()
    await audit.record(
        session, admin_user, "admin.invitation.create", "invitation", invitation.id,
        {"expires_at": invitation.expires_at.isoformat()}, actor="admin",
    )
    return invitation, token


async def list_invitations(session: AsyncSession, admin_user: User) -> list[Invitation]:
    result = await session.scalars(
        select(Invitation)
        .where(
            Invitation.created_by == admin_user.id,
            Invitation.used_at.is_(None),
            Invitation.expires_at > datetime.now(UTC),
        )
        .order_by(Invitation.created_at.desc())
    )
    return list(result)


async def revoke_invitation(session: AsyncSession, admin_user: User, invitation_id: str) -> bool:
    invitation = await session.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.created_by == admin_user.id,
            Invitation.used_at.is_(None),
        )
    )
    if invitation is None:
        return False
    await session.delete(invitation)
    await audit.record(
        session, admin_user, "admin.invitation.revoke", "invitation", invitation_id, actor="admin"
    )
    return True


async def validate_invitation(session: AsyncSession, token: str) -> bool:
    return bool(
        await session.scalar(
            text("SELECT invitation_is_valid(:token_hash)"), {"token_hash": _token_hash(token)}
        )
    )


async def consume_invitation(session: AsyncSession, token: str, user_id: str) -> bool:
    return bool(
        await session.scalar(
            text("SELECT consume_invitation(:token_hash, :user_id)"),
            {"token_hash": _token_hash(token), "user_id": user_id},
        )
    )
