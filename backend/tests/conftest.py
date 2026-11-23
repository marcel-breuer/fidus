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

from app.ai.deps import get_chat_provider, get_embedding_provider, get_web_search_provider  # noqa: E402
from app.ai.fakes import FakeChatProvider, FakeWebSearchProvider, KeywordEmbeddingProvider  # noqa: E402
from app.ai.providers import Completed, TextDelta, Usage  # noqa: E402
from app.auth.rate_limit import get_redis  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import migrate  # noqa: E402
from app.db.session import dispose_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.storage.deps import get_storage  # noqa: E402
from app.storage.memory import MemoryStorage  # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class InMemoryRateLimitStore:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.values: dict[str, int] = {}
        self.expires: dict[str, float] = {}

    def _current(self, name: str) -> int:
        if self.expires.get(name, float("inf")) <= self.clock():
            self.values.pop(name, None)
            self.expires.pop(name, None)
        return self.values.get(name, 0)

    async def eval(self, script: str, numkeys: int, *keys_and_args: str | int) -> list[int]:
        assert numkeys == 1
        name = str(keys_and_args[0])
        seconds = int(keys_and_args[1])
        value = self._current(name) + 1
        self.values[name] = value
        if value == 1:
            self.expires[name] = self.clock() + seconds
        remaining = max(0, int(self.expires[name] - self.clock()))
        return [value, remaining]


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
    original = (
        current.registration_mode,
        current.auth_rate_limit_attempts,
        current.auth_rate_limit_window_seconds,
    )
    yield current
    (
        current.registration_mode,
        current.auth_rate_limit_attempts,
        current.auth_rate_limit_window_seconds,
    ) = original


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def memory_storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
def rate_limit_store(fake_clock: FakeClock) -> InMemoryRateLimitStore:
    return InMemoryRateLimitStore(fake_clock)


@pytest.fixture
def chat_provider() -> FakeChatProvider:
    return FakeChatProvider([TextDelta("Hello"), Completed(Usage(4, 2))])


@pytest.fixture
def web_search() -> FakeWebSearchProvider:
    return FakeWebSearchProvider()


@pytest_asyncio.fixture
async def client(
    rate_limit_store: InMemoryRateLimitStore,
    chat_provider: FakeChatProvider,
    web_search: FakeWebSearchProvider,
    memory_storage: MemoryStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: rate_limit_store  # type: ignore[assignment]
    app.dependency_overrides[get_chat_provider] = lambda: chat_provider
    app.dependency_overrides[get_embedding_provider] = lambda: KeywordEmbeddingProvider()
    app.dependency_overrides[get_web_search_provider] = lambda: web_search
    app.dependency_overrides[get_storage] = lambda: memory_storage
    async def skip_index_queue(user_id: str, document_id: str) -> None:
        return None

    monkeypatch.setattr("app.services.indexing.enqueue_index_document", skip_index_queue)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
