from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI

from app.auth.rate_limit import enforce_auth_rate_limit, get_redis
from tests.conftest import FakeClock, InMemoryRateLimitStore


@pytest_asyncio.fixture
async def auth_client(
    rate_limit_store: InMemoryRateLimitStore,
) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    app.dependency_overrides[get_redis] = lambda: rate_limit_store  # type: ignore[assignment]

    @app.post("/api/v1/auth/login", dependencies=[Depends(enforce_auth_rate_limit)])
    async def login() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/auth/register", dependencies=[Depends(enforce_auth_rate_limit)])
    async def register() -> dict[str, bool]:
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
def low_rate_limit(settings):  # type: ignore[no-untyped-def]
    settings.auth_rate_limit_attempts = 2
    settings.auth_rate_limit_window_seconds = 60


@pytest.mark.usefixtures("low_rate_limit")
async def test_under_limit_passes(auth_client: httpx.AsyncClient) -> None:
    for _ in range(2):
        response = await auth_client.post(
            "/api/v1/auth/login",
            data={"username": "alice@example.com", "password": "secret"},
        )
        assert response.status_code == 200


@pytest.mark.usefixtures("low_rate_limit")
async def test_over_limit_returns_429_and_retry_after(auth_client: httpx.AsyncClient) -> None:
    for _ in range(2):
        await auth_client.post(
            "/api/v1/auth/login",
            data={"username": "alice@example.com", "password": "secret"},
        )

    response = await auth_client.post(
        "/api/v1/auth/login",
        data={"username": "alice@example.com", "password": "secret"},
    )
    assert response.status_code == 429
    assert response.json() == {"detail": "RATE_LIMITED"}
    assert response.headers["retry-after"] == "60"


@pytest.mark.usefixtures("low_rate_limit")
async def test_window_resets_with_fake_clock(
    auth_client: httpx.AsyncClient,
    fake_clock: FakeClock,
) -> None:
    for _ in range(2):
        await auth_client.post(
            "/api/v1/auth/login",
            data={"username": "alice@example.com", "password": "secret"},
        )
    blocked = await auth_client.post(
        "/api/v1/auth/login",
        data={"username": "alice@example.com", "password": "secret"},
    )
    assert blocked.status_code == 429

    fake_clock.now += 60
    allowed = await auth_client.post(
        "/api/v1/auth/login",
        data={"username": "alice@example.com", "password": "secret"},
    )
    assert allowed.status_code == 200


@pytest.mark.usefixtures("low_rate_limit")
async def test_ip_and_account_limits_apply_independently(auth_client: httpx.AsyncClient) -> None:
    for email in ("alice@example.com", "bob@example.com"):
        await auth_client.post(
            "/api/v1/auth/login",
            data={"username": email, "password": "secret"},
            headers={"X-Real-IP": "192.0.2.1"},
        )
    blocked_by_ip = await auth_client.post(
        "/api/v1/auth/login",
        data={"username": "carol@example.com", "password": "secret"},
        headers={"X-Real-IP": "192.0.2.1"},
    )
    assert blocked_by_ip.status_code == 429


@pytest.mark.usefixtures("low_rate_limit")
async def test_account_limit_is_shared_across_ips(auth_client: httpx.AsyncClient) -> None:
    for ip_address in ("192.0.2.1", "192.0.2.2"):
        await auth_client.post(
            "/api/v1/auth/login",
            data={"username": "alice@example.com", "password": "secret"},
            headers={"X-Real-IP": ip_address},
        )
    blocked_by_account = await auth_client.post(
        "/api/v1/auth/login",
        data={"username": "alice@example.com", "password": "secret"},
        headers={"X-Real-IP": "192.0.2.3"},
    )
    assert blocked_by_account.status_code == 429


@pytest.mark.usefixtures("low_rate_limit")
async def test_different_accounts_do_not_affect_each_other(auth_client: httpx.AsyncClient) -> None:
    for _ in range(3):
        await auth_client.post(
            "/api/v1/auth/login",
            data={"username": "alice@example.com", "password": "secret"},
            headers={"X-Real-IP": "192.0.2.1"},
        )
    independent = await auth_client.post(
        "/api/v1/auth/login",
        data={"username": "bob@example.com", "password": "secret"},
        headers={"X-Real-IP": "192.0.2.2"},
    )
    assert independent.status_code == 200


async def test_raw_email_and_ip_are_not_in_redis_keys(
    auth_client: httpx.AsyncClient,
    rate_limit_store: InMemoryRateLimitStore,
) -> None:
    email = "private@example.com"
    ip_address = "198.51.100.24"
    await auth_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secret"},
        headers={"X-Real-IP": ip_address},
    )

    assert rate_limit_store.values
    assert all(email not in key and ip_address not in key for key in rate_limit_store.values)



@pytest.mark.usefixtures("low_rate_limit")
async def test_real_login_and_register_routes_are_rate_limited(client: httpx.AsyncClient) -> None:
    for _ in range(2):
        response = await client.post(
            "/api/v1/auth/login", data={"username": "nobody@example.com", "password": "wrong-password"}
        )
        assert response.status_code == 400
    blocked = await client.post(
        "/api/v1/auth/login", data={"username": "nobody@example.com", "password": "wrong-password"}
    )
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "RATE_LIMITED"}

    for index in range(2):
        created = await client.post(
            "/api/v1/auth/register",
            json={"email": f"new{index}@example.com", "password": "correct-horse-battery"},
            headers={"X-Real-IP": "203.0.113.9"},
        )
        assert created.status_code == 201
    limited = await client.post(
        "/api/v1/auth/register",
        json={"email": "new2@example.com", "password": "correct-horse-battery"},
        headers={"X-Real-IP": "203.0.113.9"},
    )
    assert limited.status_code == 429
