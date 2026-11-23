"""Personal access tokens: hashed storage, scopes, expiry, revocation and bearer lookup."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiToken, User
from app.db.session import system_session
from app.modules.registry import ALL_SCOPES

TOKEN_PREFIX = "fidus_pat_"
DEFAULT_EXPIRY_DAYS = 90
MAX_EXPIRY_DAYS = 365
MAX_ACTIVE_TOKENS = 25


class InvalidScopesError(ValueError):
    """Raised for an empty scope list or a scope the instance does not define."""


class TokenLimitError(Exception):
    """Raised when a user already holds the maximum number of active tokens."""


@dataclass(frozen=True)
class TokenIdentity:
    token_id: str
    user_id: str
    scopes: frozenset[str]


def hash_token(token: str) -> str:
    # Tokens carry 256 random bits, so a plain SHA-256 is sufficient and keeps lookup indexable.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_token(
    session: AsyncSession,
    user: User,
    name: str,
    scopes: list[str],
    expires_in_days: int = DEFAULT_EXPIRY_DAYS,
    *,
    now: datetime | None = None,
) -> tuple[ApiToken, str]:
    """Create a token and return it with the plaintext secret, which is never stored."""
    unique_scopes = sorted(set(scopes))
    if not unique_scopes or not set(unique_scopes) <= ALL_SCOPES:
        raise InvalidScopesError
    if not 1 <= expires_in_days <= MAX_EXPIRY_DAYS:
        raise ValueError("expires_in_days out of range")
    now = now or datetime.now(UTC)
    active = await session.scalar(
        select(func.count()).select_from(ApiToken).where(
            ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None), ApiToken.expires_at > now
        )
    )
    if (active or 0) >= MAX_ACTIVE_TOKENS:
        raise TokenLimitError
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ApiToken(
        user_id=user.id,
        name=name.strip(),
        token_hash=hash_token(secret),
        token_prefix=secret[: len(TOKEN_PREFIX) + 4],
        scopes=unique_scopes,
        expires_at=now + timedelta(days=expires_in_days),
    )
    session.add(token)
    await session.flush()
    await session.refresh(token)
    return token, secret


async def list_tokens(session: AsyncSession, user: User) -> list[ApiToken]:
    """Unrevoked tokens of the user, newest first; expired ones stay visible so they can be removed."""
    result = await session.scalars(
        select(ApiToken)
        .where(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None))
        .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
    )
    return list(result)


async def revoke_token(session: AsyncSession, user: User, token_id: str, *, now: datetime | None = None) -> bool:
    token = await session.scalar(
        select(ApiToken).where(
            ApiToken.id == token_id, ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None)
        )
    )
    if token is None:
        return False
    token.revoked_at = now or datetime.now(UTC)
    await session.flush()
    return True


async def authenticate_token(secret: str) -> TokenIdentity | None:
    """Resolve a bearer secret to its owner. Runs before any user context exists, so it goes
    through the reviewed authenticate_api_token function instead of the row-secured table."""
    if not secret.startswith(TOKEN_PREFIX) or len(secret) > 200:
        return None
    async with system_session() as session:
        row = (
            await session.execute(
                text("SELECT token_id, user_id, scopes FROM authenticate_api_token(:token_hash)"),
                {"token_hash": hash_token(secret)},
            )
        ).first()
    if row is None:
        return None
    return TokenIdentity(token_id=row.token_id, user_id=row.user_id, scopes=frozenset(row.scopes))
