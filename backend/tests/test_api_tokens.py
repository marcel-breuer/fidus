from datetime import UTC, datetime, timedelta
from typing import get_args

import httpx
import pytest
from sqlalchemy import select, text

from app.api.tokens import Scope
from app.db.models import ApiToken, User
from app.db.session import system_session, user_session
from app.modules.registry import ALL_SCOPES
from app.services import api_tokens
from tests.helpers import PASSWORD, register


async def _login(client: httpx.AsyncClient, email: str) -> str:
    registered = await register(client, email)
    assert registered.status_code == 201
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    return registered.json()["id"]


async def _user(user_id: str) -> User:
    async with system_session() as session:
        user = await session.get(User, user_id)
    assert user is not None
    return user


def test_scope_literal_matches_registry_scopes() -> None:
    assert set(get_args(Scope)) == ALL_SCOPES


async def test_token_routes_require_a_cookie_session(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/tokens")).status_code == 401
    assert (await client.post("/api/v1/tokens", json={"name": "x", "scopes": ["tasks:read"]})).status_code == 401
    assert (await client.delete("/api/v1/tokens/missing")).status_code == 401


async def test_create_shows_secret_once_stores_hash_and_defaults_to_90_days(client: httpx.AsyncClient) -> None:
    user_id = await _login(client, "tokens-create@example.com")
    created = await client.post("/api/v1/tokens", json={"name": "  Laptop  ", "scopes": ["tasks:write", "tasks:read"]})
    assert created.status_code == 201
    body = created.json()
    secret = body["token"]
    assert secret.startswith("fidus_pat_") and body["token_prefix"] == secret[:14]
    assert body["name"] == "Laptop" and body["scopes"] == ["tasks:read", "tasks:write"]
    lifetime = datetime.fromisoformat(body["expires_at"]) - datetime.fromisoformat(body["created_at"])
    assert timedelta(days=89, hours=23) < lifetime < timedelta(days=90, minutes=5)
    assert body["last_used_at"] is None

    listed = (await client.get("/api/v1/tokens")).json()
    assert [item["id"] for item in listed] == [body["id"]]
    assert "token" not in listed[0] and secret not in (await client.get("/api/v1/tokens")).text

    async with user_session(user_id) as session:
        stored = await session.scalar(select(ApiToken).where(ApiToken.id == body["id"]))
    assert stored is not None
    assert stored.token_hash == api_tokens.hash_token(secret) and secret not in (
        stored.token_hash, stored.name, stored.token_prefix
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "x", "scopes": []},
        {"name": "x", "scopes": ["admin:all"]},
        {"name": "   ", "scopes": ["tasks:read"]},
        {"name": "x", "scopes": ["tasks:read"], "expires_in_days": 0},
        {"name": "x", "scopes": ["tasks:read"], "expires_in_days": 366},
    ],
)
async def test_create_rejects_invalid_input(client: httpx.AsyncClient, payload: dict[str, object]) -> None:
    await _login(client, "tokens-invalid@example.com")
    assert (await client.post("/api/v1/tokens", json=payload)).status_code == 422


async def test_token_creation_requires_csrf_and_is_capped(client: httpx.AsyncClient) -> None:
    await _login(client, "tokens-cap@example.com")
    bad = await client.post(
        "/api/v1/tokens", json={"name": "x", "scopes": ["tasks:read"]}, headers={"X-CSRF-Token": "bad"}
    )
    assert bad.status_code == 403
    for index in range(api_tokens.MAX_ACTIVE_TOKENS):
        payload = {"name": f"t{index}", "scopes": ["tasks:read"]}
        assert (await client.post("/api/v1/tokens", json=payload)).status_code == 201
    over = await client.post("/api/v1/tokens", json={"name": "over", "scopes": ["tasks:read"]})
    assert over.status_code == 409 and over.json()["detail"] == "TOKEN_LIMIT_REACHED"


async def test_revoke_hides_token_and_stops_authentication(client: httpx.AsyncClient) -> None:
    await _login(client, "tokens-revoke@example.com")
    body = (await client.post("/api/v1/tokens", json={"name": "x", "scopes": ["tasks:read"]})).json()
    assert await api_tokens.authenticate_token(body["token"]) is not None
    assert (await client.delete(f"/api/v1/tokens/{body['id']}")).status_code == 204
    assert (await client.get("/api/v1/tokens")).json() == []
    assert await api_tokens.authenticate_token(body["token"]) is None
    assert (await client.delete(f"/api/v1/tokens/{body['id']}")).status_code == 404


async def test_user_cannot_list_or_revoke_another_users_token(client: httpx.AsyncClient) -> None:
    await _login(client, "tokens-owner@example.com")
    owned = (await client.post("/api/v1/tokens", json={"name": "mine", "scopes": ["tasks:read"]})).json()
    client.cookies.clear()
    await _login(client, "tokens-other@example.com")
    assert (await client.get("/api/v1/tokens")).json() == []
    assert (await client.delete(f"/api/v1/tokens/{owned['id']}")).status_code == 404
    assert await api_tokens.authenticate_token(owned["token"]) is not None


async def test_authenticate_rejects_unknown_expired_and_inactive_owner(
    client: httpx.AsyncClient, owner_engine
) -> None:
    user_id = await _login(client, "tokens-auth@example.com")
    user = await _user(user_id)
    assert await api_tokens.authenticate_token("fidus_pat_unknown") is None
    assert await api_tokens.authenticate_token("not-a-token") is None

    async with user_session(user_id) as session:
        expired, expired_secret = await api_tokens.create_token(
            session, user, "old", ["tasks:read"], 1, now=datetime.now(UTC) - timedelta(days=5)
        )
        _, live_secret = await api_tokens.create_token(session, user, "live", ["tasks:read"])
    assert expired.expires_at < datetime.now(UTC)
    assert await api_tokens.authenticate_token(expired_secret) is None
    identity = await api_tokens.authenticate_token(live_secret)
    assert identity is not None and identity.user_id == user_id and identity.scopes == {"tasks:read"}

    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET is_active = false WHERE id = :id"), {"id": user_id})
    assert await api_tokens.authenticate_token(live_secret) is None


async def test_last_used_is_recorded_and_throttled(client: httpx.AsyncClient) -> None:
    user_id = await _login(client, "tokens-lastused@example.com")
    body = (await client.post("/api/v1/tokens", json={"name": "x", "scopes": ["tasks:read"]})).json()

    async def last_used() -> datetime | None:
        async with user_session(user_id) as session:
            return await session.scalar(select(ApiToken.last_used_at).where(ApiToken.id == body["id"]))

    assert await last_used() is None
    assert await api_tokens.authenticate_token(body["token"]) is not None
    first = await last_used()
    assert first is not None
    assert await api_tokens.authenticate_token(body["token"]) is not None
    assert await last_used() == first  # Within a minute: no extra write.
    listed = (await client.get("/api/v1/tokens")).json()
    assert listed[0]["last_used_at"] is not None


async def test_rls_hides_tokens_without_context_and_across_users(client: httpx.AsyncClient) -> None:
    owner_id = await _login(client, "tokens-rls-a@example.com")
    await client.post("/api/v1/tokens", json={"name": "x", "scopes": ["tasks:read"]})
    client.cookies.clear()
    other_id = await _login(client, "tokens-rls-b@example.com")

    async with system_session() as session:
        assert (await session.scalars(select(ApiToken.id))).all() == []
    async with user_session(other_id) as session:
        assert (await session.scalars(select(ApiToken.id))).all() == []
        assert (await session.scalars(select(ApiToken.id).where(ApiToken.user_id == owner_id))).all() == []
    async with user_session(owner_id) as session:
        assert len((await session.scalars(select(ApiToken.id))).all()) == 1


async def test_token_create_and_revoke_are_audited_without_the_secret(client: httpx.AsyncClient) -> None:
    await _login(client, "tokens-audit@example.com")
    body = (await client.post("/api/v1/tokens", json={"name": "x", "scopes": ["tasks:read"]})).json()
    assert (await client.delete(f"/api/v1/tokens/{body['id']}")).status_code == 204
    entries = (await client.get("/api/v1/agent/audit")).json()
    assert sorted((e["actor"], e["action"], e["target_type"], e["target_id"]) for e in entries) == [
        ("user", "token.create", "api_token", body["id"]),
        ("user", "token.revoke", "api_token", body["id"]),
    ]
    assert body["token"] not in str(entries)
    client.cookies.clear()
    await _login(client, "tokens-audit-b@example.com")
    assert (await client.get("/api/v1/agent/audit")).json() == []
