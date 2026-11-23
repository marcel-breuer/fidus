"""Container healthcheck for worker dependencies and the worker heartbeat."""

import asyncio
import sys

from redis.asyncio import Redis
from sqlalchemy import text

from app.config import get_settings
from app.db.session import dispose_engine, system_session
from app.worker.liveness import heartbeat_is_fresh


async def check() -> bool:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.ping()
        if not await heartbeat_is_fresh(redis):
            return False
        async with system_session() as session:
            await session.execute(text("SELECT 1"))
    finally:
        await redis.aclose()
        await dispose_engine()
    return True


if __name__ == "__main__":
    try:
        if not asyncio.run(check()):
            sys.exit(1)
    except Exception:
        sys.exit(1)
