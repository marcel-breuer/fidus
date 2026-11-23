from taskiq import AsyncBroker, InMemoryBroker
from taskiq_redis import ListQueueBroker

from app.config import get_settings


def build_broker(url: str | None = None, in_memory: bool = False) -> AsyncBroker:
    if in_memory:
        return InMemoryBroker()
    # BRPOP blocks until a job arrives; redis-py's default socket timeout would kill the idle worker.
    return ListQueueBroker(url or get_settings().redis_url, socket_timeout=None)


broker = build_broker()
