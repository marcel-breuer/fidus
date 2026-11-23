"""Container healthcheck: the worker is healthy when Redis and the database answer."""

import asyncio
import sys

from redis.asyncio import Redis
from sqlalchemy import text

from app.config import get_settings
from app.db.session import dispose_engine, system_session


async def check() -> bool:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.ping()
        async with system_session() as session:
            await session.execute(text("SELECT 1"))
    finally:
        await redis.aclose()
        await dispose_engine()
    return True


if __name__ == "__main__":
    try:
        asyncio.run(check())
    except Exception:
        sys.exit(1)
