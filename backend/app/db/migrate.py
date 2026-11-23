"""Entry point of the one-shot migrate service: sync the application role, then upgrade the schema."""

import asyncio
import os
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def ensure_app_role(owner_url: str | None = None) -> None:
    """Create or refresh the application role. It gets LOGIN only: no superuser,
    no BYPASSRLS, no ownership. Table privileges are granted by the migrations."""
    settings = get_settings()
    role = settings.app_db_user
    engine = create_async_engine(owner_url or settings.database_owner_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        exists = await conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
        verb = "ALTER" if exists else "CREATE"
        # Passwords cannot be bound parameters in DDL; escape the literal instead.
        password = settings.app_db_password.replace("'", "''")
        await conn.execute(
            text(
                f"{verb} ROLE {_quote_ident(role)} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB "
                f"NOCREATEROLE NOINHERIT PASSWORD '{password}'"
            ).execution_options(no_parameters=True)
        )
        db_name = await conn.scalar(text("SELECT current_database()"))
        await conn.execute(text(f"GRANT CONNECT ON DATABASE {_quote_ident(db_name)} TO {_quote_ident(role)}"))
    await engine.dispose()


def upgrade_schema() -> None:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=os.environ.copy())


def main() -> None:
    asyncio.run(ensure_app_role())
    upgrade_schema()


if __name__ == "__main__":
    main()
