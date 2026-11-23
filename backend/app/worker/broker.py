import asyncio

from redis.asyncio import Redis
from taskiq import AsyncBroker, InMemoryBroker, TaskiqEvents, TaskiqState
from taskiq_redis import ListQueueBroker

from app.config import get_settings
from app.worker.liveness import HEARTBEAT_KEY, heartbeat_loop, refresh_heartbeat


def build_broker(url: str | None = None, in_memory: bool = False) -> AsyncBroker:
    if in_memory:
        return InMemoryBroker()
    # BRPOP blocks until a job arrives; redis-py's default socket timeout would kill the idle worker.
    return ListQueueBroker(url or get_settings().redis_url, socket_timeout=None)


broker = build_broker()


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def start_heartbeat(state: TaskiqState) -> None:
    redis = Redis.from_url(get_settings().redis_url)
    await refresh_heartbeat(redis)
    state.heartbeat_redis = redis
    state.heartbeat_task = asyncio.create_task(heartbeat_loop(redis))


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def stop_heartbeat(state: TaskiqState) -> None:
    task = state.heartbeat_task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    redis: Redis = state.heartbeat_redis
    try:
        await redis.delete(HEARTBEAT_KEY)
    finally:
        await redis.aclose()
