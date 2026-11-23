"""Database-backed authentication strategy with revocable opaque tokens."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi_users import BaseUserManager
from fastapi_users.authentication.strategy import Strategy
from fastapi_users.exceptions import UserNotExists

from app.config import get_settings
from app.db.models import Session, User
from app.db.session import get_sessionmaker


class DatabaseSessionStrategy(Strategy[User, str]):
    async def read_token(
        self, token: str | None, user_manager: BaseUserManager[User, str]
    ) -> User | None:
        if not token:
            return None

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        async with get_sessionmaker()() as session:
            auth_session = await session.get(Session, token_hash)
        if auth_session is None or auth_session.expires_at <= datetime.now(UTC):
            return None

        try:
            # Inactive users are rejected by the current_user(active=True) dependency.
            return await user_manager.get(auth_session.user_id)
        except UserNotExists:
            return None

    async def write_token(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        auth_session = Session(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(seconds=get_settings().session_lifetime_seconds),
        )
        async with get_sessionmaker()() as session:
            session.add(auth_session)
            await session.commit()
        return token

    async def destroy_token(self, token: str, user: User) -> None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        async with get_sessionmaker()() as session:
            auth_session = await session.get(Session, token_hash)
            if auth_session is not None and auth_session.user_id == user.id:
                await session.delete(auth_session)
                await session.commit()
