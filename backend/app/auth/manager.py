from collections.abc import AsyncIterator

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers
from fastapi_users.authentication import AuthenticationBackend, CookieTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import UserCreate
from app.config import get_settings
from app.db.models import User
from app.db.session import get_sessionmaker

COOKIE_NAME = "fidus_session"
# Serializes registrations so exactly one "first user" exists.
_REGISTRATION_LOCK = 727_001


class RegistrationClosedError(Exception):
    """Raised when REGISTRATION_MODE does not allow another account."""


class UserManager(BaseUserManager[User, str]):
    def __init__(self, user_db: SQLAlchemyUserDatabase[User, str]) -> None:
        super().__init__(user_db)
        secret = get_settings().secret_key
        self.reset_password_token_secret = secret
        self.verification_token_secret = secret

    def parse_id(self, value: object) -> str:
        return str(value)

    async def create(
        self, user_create: UserCreate, safe: bool = False, request: Request | None = None
    ) -> User:
        session: AsyncSession = self.user_db.session
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _REGISTRATION_LOCK})
        existing = await session.scalar(select(func.count()).select_from(User))
        if existing:
            if get_settings().registration_mode != "open":
                await session.rollback()
                raise RegistrationClosedError
            return await super().create(user_create, safe=True, request=request)
        # The first account bootstraps the instance, whatever the registration mode.
        first = user_create.model_copy(update={"is_superuser": True})
        return await super().create(first, safe=False, request=request)


async def get_auth_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def get_user_db(
    session: AsyncSession = Depends(get_auth_session),
) -> AsyncIterator[SQLAlchemyUserDatabase[User, str]]:
    yield SQLAlchemyUserDatabase(session, User)


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase[User, str] = Depends(get_user_db),
) -> AsyncIterator[UserManager]:
    yield UserManager(user_db)


def _strategy() -> JWTStrategy[User, str]:
    settings = get_settings()
    return JWTStrategy(secret=settings.secret_key, lifetime_seconds=settings.session_lifetime_seconds)


def _transport() -> CookieTransport:
    settings = get_settings()
    return CookieTransport(
        cookie_name=COOKIE_NAME,
        cookie_max_age=settings.session_lifetime_seconds,
        cookie_secure=settings.cookie_secure,
        cookie_httponly=True,
        cookie_samesite="lax",
    )


auth_backend = AuthenticationBackend(name="cookie", transport=_transport(), get_strategy=_strategy)
fastapi_users = FastAPIUsers[User, str](get_user_manager, [auth_backend])
current_active_user = fastapi_users.current_user(active=True)
