import pytest

from app.worker.liveness import (
    HEARTBEAT_INTERVAL_SECONDS,
    HEARTBEAT_KEY,
    HEARTBEAT_TTL_SECONDS,
    heartbeat_is_fresh,
    heartbeat_loop,
    refresh_heartbeat,
)


class FakeRedis:
    def __init__(self) -> None:
        self.now = 1_000.0
        self.values: dict[str, tuple[str, float]] = {}

    async def set(self, key: str, value: str, ex: int) -> None:
        self.values[key] = (value, self.now + ex)

    async def get(self, key: str) -> str | None:
        entry = self.values.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at <= self.now:
            del self.values[key]
            return None
        return value


async def test_heartbeat_is_fresh_until_its_ttl_expires() -> None:
    redis = FakeRedis()

    await refresh_heartbeat(redis, clock=lambda: redis.now)

    assert await heartbeat_is_fresh(redis, clock=lambda: redis.now)
    redis.now += HEARTBEAT_TTL_SECONDS
    assert not await heartbeat_is_fresh(redis, clock=lambda: redis.now)
    assert await redis.get(HEARTBEAT_KEY) is None


async def test_heartbeat_loop_refreshes_periodically() -> None:
    redis = FakeRedis()
    sleeps = 0

    class StopLoop(Exception):
        pass

    async def advance_clock(interval: float) -> None:
        nonlocal sleeps
        assert interval == HEARTBEAT_INTERVAL_SECONDS
        sleeps += 1
        redis.now += interval
        if sleeps == 2:
            raise StopLoop

    with pytest.raises(StopLoop):
        await heartbeat_loop(redis, sleep=advance_clock, clock=lambda: redis.now)

    assert redis.values[HEARTBEAT_KEY][0] == "1010.0"


async def test_missing_or_malformed_heartbeat_is_unhealthy() -> None:
    redis = FakeRedis()

    assert not await heartbeat_is_fresh(redis, clock=lambda: redis.now)

    redis.values[HEARTBEAT_KEY] = ("not-a-timestamp", redis.now + HEARTBEAT_TTL_SECONDS)
    assert not await heartbeat_is_fresh(redis, clock=lambda: redis.now)


async def test_heartbeat_loop_survives_a_failed_refresh() -> None:
    redis = FakeRedis()
    calls = 0
    original_set = redis.set

    async def flaky_set(key: str, value: str, ex: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("redis down")
        await original_set(key, value, ex)

    redis.set = flaky_set  # type: ignore[method-assign]
    sleeps = 0

    class StopLoop(Exception):
        pass

    async def advance_clock(interval: float) -> None:
        nonlocal sleeps
        sleeps += 1
        redis.now += interval
        if sleeps == 2:
            raise StopLoop

    with pytest.raises(StopLoop):
        await heartbeat_loop(redis, sleep=advance_clock, clock=lambda: redis.now)

    assert await heartbeat_is_fresh(redis, clock=lambda: redis.now)
