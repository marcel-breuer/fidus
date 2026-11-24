from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI

from app.auth.rate_limit import enforce_auth_rate_limit, get_redis
from app.db.models import User
from app.db.session import user_session
from app.services import conversations
from tests.conftest import FakeClock, InMemoryRateLimitStore
from tests.helpers import PASSWORD, register


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


async def test_paid_operations_have_isolated_per_user_limits(
    client: httpx.AsyncClient, settings, memory_storage
) -> None:  # type: ignore[no-untyped-def]
    settings.chat_rate_limit_requests = 1
    settings.file_upload_rate_limit_requests = 1
    settings.transcription_rate_limit_requests = 1
    settings.chat_rate_limit_window_seconds = 60
    settings.file_upload_rate_limit_window_seconds = 60
    settings.transcription_rate_limit_window_seconds = 60
    alice = (await register(client, "limit-alice@example.com")).json()
    bob = (await register(client, "limit-bob@example.com")).json()

    async def login(email: str) -> None:
        response = await client.post(
            "/api/v1/auth/login", data={"username": email, "password": PASSWORD}
        )
        assert response.status_code == 204
        client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""

    async def create_conversation(user_id: str) -> str:
        async with user_session(user_id) as session:
            user = await session.get(User, user_id)
            assert user is not None
            return (await conversations.create_conversation(session, user, None)).id

    await login("limit-alice@example.com")
    alice_conversation = await create_conversation(alice["id"])
    chat_path = f"/api/v1/conversations/{alice_conversation}/messages/stream"
    assert (await client.post(chat_path, json={"content": "hello"})).status_code == 200
    limited_chat = await client.post(chat_path, json={"content": "again"})
    assert limited_chat.status_code == 429
    assert limited_chat.headers["retry-after"] == "60"

    assert (
        await client.post(
            "/api/v1/files/upload", files={"file": ("note.txt", b"safe text", "text/plain")}
        )
    ).status_code == 201
    limited_upload = await client.post(
        "/api/v1/files/upload", files={"file": ("another.txt", b"safe", "text/plain")}
    )
    assert limited_upload.status_code == 429
    assert limited_upload.headers["retry-after"] == "60"

    audio_data = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
    assert (
        await client.post(
            "/api/v1/audio/memos",
            files={"file": ("note.webm", audio_data, "audio/webm")},
        )
    ).status_code == 201
    limited_transcription = await client.post(
        "/api/v1/audio/memos",
        files={"file": ("another.webm", audio_data, "audio/webm")},
    )
    assert limited_transcription.status_code == 429
    assert limited_transcription.headers["retry-after"] == "60"

    await login("limit-bob@example.com")
    bob_conversation = await create_conversation(bob["id"])
    assert (
        await client.post(
            f"/api/v1/conversations/{bob_conversation}/messages/stream",
            json={"content": "hello"},
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/files/upload", files={"file": ("note.txt", b"safe", "text/plain")}
        )
    ).status_code == 201
    assert (
        await client.post(
            "/api/v1/audio/memos",
            files={"file": ("note.webm", audio_data, "audio/webm")},
        )
    ).status_code == 201
