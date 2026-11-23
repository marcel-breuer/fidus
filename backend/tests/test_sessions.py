import hashlib
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, text

from app.db.models import Session
from app.db.session import get_sessionmaker
from app.main import create_app
from app.services.sessions import purge_expired_sessions, revoke_all_sessions
from tests.helpers import login, register


async def test_login_stores_only_a_hash_and_me_works(
    client: httpx.AsyncClient, owner_engine
) -> None:
    await register(client, "user@example.com")

    response = await login(client, "user@example.com")
    raw_token = client.cookies.get("fidus_session")

    assert response.status_code == 204
    assert raw_token is not None
    async with owner_engine.connect() as connection:
        stored_hash = await connection.scalar(select(Session.token_hash))
    assert stored_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert stored_hash != raw_token
    assert (await client.get("/api/v1/users/me")).status_code == 200


async def test_logout_deletes_session_and_replayed_cookie_is_rejected(
    client: httpx.AsyncClient, owner_engine
) -> None:
    await register(client, "user@example.com")
    await login(client, "user@example.com")
    raw_token = client.cookies.get("fidus_session")
    csrf_token = client.cookies.get("fidus_csrf")
    assert raw_token is not None and csrf_token is not None

    response = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf_token})
    assert response.status_code == 204
    async with owner_engine.connect() as connection:
        session_count = await connection.scalar(select(Session.token_hash))
    assert session_count is None

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as replay_client:
        replay_client.cookies.set("fidus_session", raw_token)
        assert (await replay_client.get("/api/v1/users/me")).status_code == 401


async def test_expired_session_is_rejected(client: httpx.AsyncClient, owner_engine) -> None:
    await register(client, "user@example.com")
    await login(client, "user@example.com")
    raw_token = client.cookies.get("fidus_session")
    assert raw_token is not None
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("UPDATE sessions SET expires_at = :expires_at WHERE token_hash = :token_hash"),
            {"expires_at": datetime.now(UTC) - timedelta(seconds=1), "token_hash": token_hash},
        )

    assert (await client.get("/api/v1/users/me")).status_code == 401


async def test_deactivated_user_session_is_rejected(
    client: httpx.AsyncClient, owner_engine
) -> None:
    user = await register(client, "user@example.com")
    await login(client, "user@example.com")
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"), {"id": user.json()["id"]}
        )

    assert (await client.get("/api/v1/users/me")).status_code == 401


async def test_revoke_all_sessions_only_removes_target_users_sessions(
    client: httpx.AsyncClient, owner_engine
) -> None:
    first = await register(client, "first@example.com")
    second = await register(client, "second@example.com")
    await login(client, "first@example.com")
    await login(client, "first@example.com")
    await login(client, "second@example.com")
    first_id = first.json()["id"]
    second_id = second.json()["id"]

    async with get_sessionmaker()() as session, session.begin():
        removed = await revoke_all_sessions(session, first_id)
    async with owner_engine.connect() as connection:
        remaining = list((await connection.scalars(select(Session.user_id))).all())

    assert removed == 2
    assert remaining == [second_id]


async def test_purge_expired_sessions_keeps_unexpired_sessions(
    client: httpx.AsyncClient, owner_engine
) -> None:
    expired_user = await register(client, "expired@example.com")
    current_user = await register(client, "current@example.com")
    await login(client, "expired@example.com")
    await login(client, "current@example.com")
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("UPDATE sessions SET expires_at = :expires_at WHERE user_id = :user_id"),
            {
                "expires_at": datetime.now(UTC) - timedelta(seconds=1),
                "user_id": expired_user.json()["id"],
            },
        )

    async with get_sessionmaker()() as session, session.begin():
        removed = await purge_expired_sessions(session)
    async with owner_engine.connect() as connection:
        remaining = list((await connection.scalars(select(Session.user_id))).all())

    assert removed == 1
    assert remaining == [current_user.json()["id"]]
