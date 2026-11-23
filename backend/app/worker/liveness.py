"""Heartbeat helpers for the Taskiq worker process."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "fidus:worker:heartbeat"
HEARTBEAT_INTERVAL_SECONDS = 10
HEARTBEAT_TTL_SECONDS = 30


class HeartbeatRedis(Protocol):
    async def set(self, key: str, value: str, ex: int) -> object: ...

    async def get(self, key: str) -> str | bytes | None: ...


async def refresh_heartbeat(
    redis: HeartbeatRedis,
    clock: Callable[[], float] | None = None,
) -> None:
    """Write the current time and let Redis expire old heartbeats."""
    now = (clock or time.time)()
    await redis.set(HEARTBEAT_KEY, str(now), ex=HEARTBEAT_TTL_SECONDS)


async def heartbeat_loop(
    redis: HeartbeatRedis,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] | None = None,
) -> None:
    while True:
        try:
            await refresh_heartbeat(redis, clock)
        except Exception:
            # A Redis hiccup must not end the loop for good; the TTL already
            # turns a long outage into an unhealthy worker.
            logger.warning("Worker heartbeat refresh failed", exc_info=True)
        await sleep(HEARTBEAT_INTERVAL_SECONDS)


async def heartbeat_is_fresh(
    redis: HeartbeatRedis,
    clock: Callable[[], float] | None = None,
) -> bool:
    value = await redis.get(HEARTBEAT_KEY)
    if value is None:
        return False

    try:
        heartbeat_time = float(value)
    except (TypeError, ValueError):
        return False

    age = (clock or time.time)() - heartbeat_time
    return 0 <= age <= HEARTBEAT_TTL_SECONDS
