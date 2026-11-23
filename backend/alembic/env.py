import asyncio
import os

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.config import get_settings
from app.db import models  # noqa: F401  (registers tables on the metadata)
from app.db.base import Base

target_metadata = Base.metadata


def _url() -> str:
    # Migrations always run as the owner role. MIGRATION_DATABASE_URL lets tests target a scratch database.
    return os.environ.get("MIGRATION_DATABASE_URL") or get_settings().database_owner_url


def _run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


asyncio.run(_run_async())
