from datetime import datetime, timedelta, timezone
import hashlib

import httpx
from sqlalchemy import select, text

from app.db.models import Invitation
from app.db.session import get_sessionmaker, set_user_context
from tests.helpers import PASSWORD, login, register


async def _admin(client: httpx.AsyncClient, settings) -> dict[str, str]:
    settings.registration_mode = "invite-only"
    response = await register(client, "admin@example.com")
    assert response.status_code == 201
    await login(client, "admin@example.com")
    return response.json()


async def _invitation(client: httpx.AsyncClient) -> dict[str, object]:
    response = await client.post("/api/v1/invitations", json={})
    assert response.status_code == 201
    return response.json()


async def test_admin_creates_one_time_hashed_invitation_and_member_is_forbidden(
    client: httpx.AsyncClient, settings, owner_engine
) -> None:
    admin = await _admin(client, settings)
    created = await _invitation(client)
    token = str(created["token"])
    assert created["id"]
    assert created["expires_at"]

    listed = await client.get("/api/v1/invitations")
    assert listed.status_code == 200
    assert listed.json() == [{"id": created["id"], "expires_at": created["expires_at"]}]
    assert "token" not in listed.json()[0]
    async with owner_engine.connect() as connection:
        stored = await connection.scalar(
            select(Invitation.token_hash).where(Invitation.id == created["id"])
        )
    assert stored == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored

    settings.registration_mode = "open"
    member = await register(client, "member@example.com")
    assert member.status_code == 201
    await login(client, "member@example.com")
    assert (await client.post("/api/v1/invitations", json={})).status_code == 403
    assert admin["role"] == "admin"


async def test_invitation_endpoints_require_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/v1/invitations", json={})).status_code == 401
    assert (await client.get("/api/v1/invitations")).status_code == 401
    assert (await client.delete("/api/v1/invitations/01J00000000000000000000000")).status_code == 401


async def test_invite_only_registration_consumes_token_once(
    client: httpx.AsyncClient, settings
) -> None:
    await _admin(client, settings)
    invitation = await _invitation(client)
    token = str(invitation["token"])
    accepted = await client.post(
        "/api/v1/auth/register",
        json={"email": "invited@example.com", "password": PASSWORD, "invitation_token": token},
    )
    assert accepted.status_code == 201
    replayed = await client.post(
        "/api/v1/auth/register",
        json={"email": "replay@example.com", "password": PASSWORD, "invitation_token": token},
    )
    assert replayed.status_code == 403
    assert replayed.json()["detail"] == "REGISTRATION_CLOSED"


async def test_invite_only_rejects_missing_expired_and_revoked_tokens(
    client: httpx.AsyncClient, settings, owner_engine
) -> None:
    await _admin(client, settings)
    missing = await register(client, "missing@example.com")
    assert missing.status_code == 403

    expired = await _invitation(client)
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("UPDATE invitations SET expires_at = :past WHERE id = :id"),
            {"past": datetime.now(timezone.utc) - timedelta(days=1), "id": expired["id"]},
        )
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "expired@example.com", "password": PASSWORD, "invitation_token": expired["token"]},
    )
    assert response.status_code == 403

    revoked = await _invitation(client)
    assert (await client.delete(f"/api/v1/invitations/{revoked['id']}")).status_code == 204
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "revoked@example.com", "password": PASSWORD, "invitation_token": revoked["token"]},
    )
    assert response.status_code == 403


async def test_duplicate_registration_does_not_consume_invitation(
    client: httpx.AsyncClient, settings
) -> None:
    await _admin(client, settings)
    settings.registration_mode = "open"
    assert (await register(client, "duplicate@example.com")).status_code == 201
    settings.registration_mode = "invite-only"
    invitation = await _invitation(client)
    duplicate = await client.post(
        "/api/v1/auth/register",
        json={"email": "duplicate@example.com", "password": PASSWORD, "invitation_token": invitation["token"]},
    )
    assert duplicate.status_code == 400
    subsequent = await client.post(
        "/api/v1/auth/register",
        json={"email": "subsequent@example.com", "password": PASSWORD, "invitation_token": invitation["token"]},
    )
    assert subsequent.status_code == 201


async def test_user_cannot_read_or_revoke_another_admins_invitations(
    client: httpx.AsyncClient, settings, owner_engine
) -> None:
    admin = await _admin(client, settings)
    invitation = await _invitation(client)
    settings.registration_mode = "open"
    member = await register(client, "second-admin@example.com")
    assert member.status_code == 201
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("UPDATE users SET is_superuser = true WHERE id = :id"), {"id": member.json()["id"]}
        )
    await login(client, "second-admin@example.com")
    assert (await client.get("/api/v1/invitations")).json() == []
    assert (await client.delete(f"/api/v1/invitations/{invitation['id']}")).status_code == 404

    async with get_sessionmaker()() as session, session.begin():
        await set_user_context(session, member.json()["id"])
        row = await session.scalar(
            select(Invitation).where(Invitation.id == invitation["id"])
        )
    assert row is None

    await login(client, "admin@example.com")
    assert [row["id"] for row in (await client.get("/api/v1/invitations")).json()] == [invitation["id"]]
    assert admin["role"] == "admin"


async def test_public_cannot_execute_invitation_functions(owner_engine) -> None:
    async with owner_engine.connect() as connection:
        public_can_execute = await connection.scalar(
            text(
                """SELECT EXISTS (
                    SELECT 1 FROM pg_proc p, LATERAL aclexplode(
                        coalesce(p.proacl, acldefault('f', p.proowner))
                    ) a
                    WHERE p.proname IN ('invitation_is_valid', 'consume_invitation')
                      AND a.grantee = 0 AND a.privilege_type = 'EXECUTE'
                )"""
            )
        )
    assert public_can_execute is False
