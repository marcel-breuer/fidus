"""Test harness. Tests never touch the configured database: they build a scratch
database `<name>_test` on the same server through the owner role, migrate it with
the real Alembic migrations and connect as a test-specific application role."""

import asyncio
import os
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

_DEFAULT_OWNER = "postgresql+asyncpg://fidus:change-me@db:5432/fidus"
_DEFAULT_APP = "postgresql+asyncpg://fidus_app:change-me@db:5432/fidus"

_owner_url = make_url(os.environ.get("DATABASE_OWNER_URL", _DEFAULT_OWNER))
_app_url = make_url(os.environ.get("DATABASE_URL", _DEFAULT_APP))
_test_db = f"{_owner_url.database}_test"
_app_role = os.environ.get("APP_DB_USER") or _app_url.username or "fidus_app"
_test_role = f"{_app_role}_test"
OWNER_URL = _owner_url.set(database=_test_db).render_as_string(hide_password=False)
APP_URL = _app_url.set(database=_test_db, username=_test_role).render_as_string(hide_password=False)
ADMIN_URL = _owner_url.set(database="postgres").render_as_string(hide_password=False)

os.environ["DATABASE_OWNER_URL"] = OWNER_URL
os.environ["DATABASE_URL"] = APP_URL
os.environ["MIGRATION_DATABASE_URL"] = OWNER_URL
os.environ["APP_DB_USER"] = _test_role
os.environ["APP_DB_PASSWORD"] = _app_url.password or "change-me"
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only")
os.environ["REGISTRATION_MODE"] = "open"
os.environ["APP_URL"] = "http://localhost:8080"

from app.config import get_settings  # noqa: E402
from app.db import migrate  # noqa: E402
from app.db.session import dispose_engine  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    async def create() -> None:
        engine = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_test_db}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{_test_db}"'))
        await engine.dispose()
        await migrate.ensure_app_role(OWNER_URL)

    asyncio.run(create())
    migrate.upgrade_schema()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    engine = create_async_engine(OWNER_URL)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users CASCADE"))
    await engine.dispose()
    yield
    await dispose_engine()


@pytest.fixture
def owner_engine():  # type: ignore[no-untyped-def]
    return create_async_engine(OWNER_URL)


@pytest.fixture
def settings():  # type: ignore[no-untyped-def]
    current = get_settings()
    original = current.registration_mode
    yield current
    current.registration_mode = original


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
