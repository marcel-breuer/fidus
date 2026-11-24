import httpx
import pytest
from sqlalchemy import text

from app.db.models import User
from app.db.session import user_session
from app.services import admin_users
from tests.helpers import PASSWORD, login, register


async def _login(client: httpx.AsyncClient, email: str) -> None:
    response = await login(client, email)
    assert response.status_code in (200, 204)
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""


async def _users(client: httpx.AsyncClient) -> dict[str, dict]:
    response = await client.get("/api/v1/admin/users")
    assert response.status_code == 200
    return {item["email"]: item for item in response.json()["items"]}


async def _setup(client: httpx.AsyncClient) -> dict[str, dict]:
    """Admin, member and a second admin, with the client logged in as the first admin."""
    for email in ("admin@example.com", "member@example.com"):
        assert (await register(client, email)).status_code == 201
    await _login(client, "admin@example.com")
    return await _users(client)


async def _audit(owner_engine, action: str) -> list[dict]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT a.actor, a.target_type, a.target_id, a.details, u.email "
                "FROM audit_log a JOIN users u ON u.id = a.user_id WHERE a.action = :action"
            ),
            {"action": action},
        )
        return [dict(row._mapping) for row in rows]


async def test_admin_endpoints_reject_anonymous_and_member(client: httpx.AsyncClient) -> None:
    users = await _setup(client)
    member_id = users["member@example.com"]["id"]
    anonymous = httpx.AsyncClient(transport=client._transport, base_url="http://test")
    assert (await anonymous.get("/api/v1/admin/users")).status_code == 401
    assert (await anonymous.get("/api/v1/admin/registration")).status_code == 401

    await _login(client, "member@example.com")
    assert (await client.get("/api/v1/admin/users")).status_code == 403
    assert (await client.get("/api/v1/admin/audit")).status_code == 403
    patch = await client.patch(f"/api/v1/admin/users/{member_id}", json={"role": "admin"})
    assert patch.status_code == 403
    assert (await client.get("/api/v1/admin/registration")).status_code == 403
    assert (await client.put("/api/v1/admin/registration", json={"mode": "closed"})).status_code == 403
    assert (await client.get("/api/v1/users/me")).json()["role"] == "member"


async def test_admin_lists_users(client: httpx.AsyncClient) -> None:
    users = await _setup(client)
    assert users["admin@example.com"]["role"] == "admin"
    assert users["member@example.com"] == {
        "id": users["member@example.com"]["id"], "email": "member@example.com", "role": "member",
        "is_active": True, "created_at": users["member@example.com"]["created_at"],
    }
    assert "hashed_password" not in users["member@example.com"]


async def test_admin_user_search_and_cursor_pagination(client: httpx.AsyncClient) -> None:
    await _setup(client)
    assert (await register(client, "alpha@example.com")).status_code == 201
    assert (await register(client, "beta@example.com")).status_code == 201
    search = await client.get("/api/v1/admin/users", params={"q": "BETA"})
    assert [item["email"] for item in search.json()["items"]] == ["beta@example.com"]
    wildcard_search = await client.get("/api/v1/admin/users", params={"q": "%"})
    assert wildcard_search.json()["items"] == []
    first = await client.get("/api/v1/admin/users", params={"limit": 1})
    assert first.status_code == 200 and first.json()["next_cursor"]
    second = await client.get(
        "/api/v1/admin/users", params={"limit": 1, "cursor": first.json()["next_cursor"]}
    )
    assert second.status_code == 200
    assert first.json()["items"][0]["id"] != second.json()["items"][0]["id"]
    assert (await client.get("/api/v1/admin/users", params={"cursor": "invalid"})).status_code == 400


async def test_admin_audit_is_instance_wide_and_paged_only_for_admins(
    client: httpx.AsyncClient, owner_engine
) -> None:
    users = await _setup(client)
    member = await register(client, "second-admin@example.com")
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("UPDATE users SET is_superuser = true WHERE id = :id"), {"id": member.json()["id"]}
        )
    await client.post("/api/v1/invitations", json={})
    await _login(client, "second-admin@example.com")
    response = await client.get("/api/v1/admin/audit", params={"limit": 1})
    assert response.status_code == 200 and response.json()["items"]
    assert response.json()["items"][0]["action"] == "admin.invitation.create"
    cursor = response.json()["next_cursor"]
    if cursor:
        following = await client.get("/api/v1/admin/audit", params={"limit": 1, "cursor": cursor})
        assert following.status_code == 200
        assert following.json()["items"][0]["id"] != response.json()["items"][0]["id"]
    async with user_session(users["member@example.com"]["id"]) as session:
        assert await session.scalar(text("SELECT count(*) FROM admin_list_audit_entries(NULL, NULL, 10)")) == 0
    assert users["admin@example.com"]["role"] == "admin"


async def test_deactivation_locks_user_out_and_is_audited(
    client: httpx.AsyncClient, owner_engine
) -> None:
    users = await _setup(client)
    member = users["member@example.com"]
    member_client = httpx.AsyncClient(transport=client._transport, base_url="http://test")
    await _login(member_client, "member@example.com")
    assert (await member_client.get("/api/v1/users/me")).status_code == 200

    response = await client.patch(f"/api/v1/admin/users/{member['id']}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert (await member_client.get("/api/v1/users/me")).status_code == 401
    assert (await login(member_client, "member@example.com")).status_code == 400
    async with owner_engine.connect() as conn:
        assert await conn.scalar(
            text("SELECT count(*) FROM sessions WHERE user_id = :id"), {"id": member["id"]}
        ) == 0

    entries = await _audit(owner_engine, "admin.user.deactivate")
    assert len(entries) == 1
    assert entries[0]["email"] == "admin@example.com"
    assert entries[0]["actor"] == "admin"
    assert entries[0]["target_type"] == "user"
    assert entries[0]["target_id"] == member["id"]

    reactivated = await client.patch(f"/api/v1/admin/users/{member['id']}", json={"is_active": True})
    assert reactivated.json()["is_active"] is True
    await _login(member_client, "member@example.com")
    assert (await member_client.get("/api/v1/users/me")).status_code == 200
    assert len(await _audit(owner_engine, "admin.user.activate")) == 1


async def test_noop_update_writes_no_audit_entry(client: httpx.AsyncClient, owner_engine) -> None:
    users = await _setup(client)
    member_id = users["member@example.com"]["id"]
    response = await client.patch(
        f"/api/v1/admin/users/{member_id}", json={"is_active": True, "role": "member"}
    )
    assert response.status_code == 200
    assert await _audit(owner_engine, "admin.user.activate") == []
    assert await _audit(owner_engine, "admin.user.role") == []


async def test_role_change_promotes_and_demotes_with_audit(
    client: httpx.AsyncClient, owner_engine
) -> None:
    users = await _setup(client)
    member_id = users["member@example.com"]["id"]
    promoted = await client.patch(f"/api/v1/admin/users/{member_id}", json={"role": "admin"})
    assert promoted.json()["role"] == "admin"
    entries = await _audit(owner_engine, "admin.user.role")
    assert entries[0]["details"] == {"from": "member", "to": "admin"}

    # The promoted admin may now administer; the original admin can be demoted by them.
    await _login(client, "member@example.com")
    assert (await client.get("/api/v1/admin/users")).status_code == 200
    demoted = await client.patch(
        f"/api/v1/admin/users/{users['admin@example.com']['id']}", json={"role": "member"}
    )
    assert demoted.json()["role"] == "member"
    await _login(client, "admin@example.com")
    assert (await client.get("/api/v1/admin/users")).status_code == 403


async def test_admin_cannot_deactivate_or_demote_self(client: httpx.AsyncClient) -> None:
    users = await _setup(client)
    own_id = users["admin@example.com"]["id"]
    for body in ({"is_active": False}, {"role": "member"}):
        response = await client.patch(f"/api/v1/admin/users/{own_id}", json=body)
        assert response.status_code == 409
        assert response.json()["detail"] == "CANNOT_MODIFY_SELF"
    assert (await _users(client))["admin@example.com"]["role"] == "admin"


async def test_last_active_admin_cannot_be_removed(client: httpx.AsyncClient) -> None:
    users = await _setup(client)
    admin_id, member_id = users["admin@example.com"]["id"], users["member@example.com"]["id"]
    await client.patch(f"/api/v1/admin/users/{member_id}", json={"role": "admin"})
    # Second admin goes inactive, so the first is the only active admin left.
    await client.patch(f"/api/v1/admin/users/{member_id}", json={"is_active": False})
    # Even a stale actor (a different, no longer active admin) cannot remove the last one.
    stale = User(id=member_id, email="member@example.com", is_superuser=True, is_active=True)
    async with user_session(member_id) as session:
        for kwargs in ({"is_active": False}, {"is_admin": False}):
            with pytest.raises(admin_users.LastAdminError):
                await admin_users.update_user(session, stale, admin_id, **kwargs)


async def test_unknown_user_and_empty_update(client: httpx.AsyncClient) -> None:
    await _setup(client)
    missing = await client.patch("/api/v1/admin/users/no-such-user", json={"is_active": False})
    assert missing.status_code == 404
    empty = await client.patch("/api/v1/admin/users/no-such-user", json={})
    assert empty.status_code == 422
    bad_role = await client.patch("/api/v1/admin/users/x", json={"role": "root"})
    assert bad_role.status_code == 422


async def test_registration_mode_override_applies_at_runtime(
    client: httpx.AsyncClient, settings, owner_engine
) -> None:
    await _setup(client)
    initial = await client.get("/api/v1/admin/registration")
    assert initial.json() == {"mode": "open", "default": "open", "overridden": False}

    updated = await client.put("/api/v1/admin/registration", json={"mode": "invite-only"})
    assert updated.json() == {"mode": "invite-only", "default": "open", "overridden": True}
    anonymous = httpx.AsyncClient(transport=client._transport, base_url="http://test")
    blocked = await register(anonymous, "late@example.com")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "REGISTRATION_CLOSED"

    await client.put("/api/v1/admin/registration", json={"mode": "closed"})
    assert (await register(anonymous, "late@example.com")).status_code == 403

    await client.put("/api/v1/admin/registration", json={"mode": "open"})
    assert (await register(anonymous, "late@example.com")).status_code == 201

    entries = await _audit(owner_engine, "admin.registration_mode.set")
    assert [entry["details"] for entry in entries] == [
        {"from": "open", "to": "invite-only"},
        {"from": "invite-only", "to": "closed"},
        {"from": "closed", "to": "open"},
    ]


async def test_registration_override_beats_environment_default(
    client: httpx.AsyncClient, settings
) -> None:
    await _setup(client)
    settings.registration_mode = "closed"
    assert (await client.get("/api/v1/admin/registration")).json()["mode"] == "closed"
    await client.put("/api/v1/admin/registration", json={"mode": "open"})
    anonymous = httpx.AsyncClient(transport=client._transport, base_url="http://test")
    assert (await register(anonymous, "late@example.com")).status_code == 201


async def test_invalid_registration_mode_is_rejected(client: httpx.AsyncClient) -> None:
    await _setup(client)
    assert (await client.put("/api/v1/admin/registration", json={"mode": "public"})).status_code == 422


async def test_admin_cannot_read_member_data_and_audit_is_scoped(
    client: httpx.AsyncClient, owner_engine
) -> None:
    users = await _setup(client)
    await _login(client, "member@example.com")
    assert (await client.post("/api/v1/tasks", json={"title": "Private"})).status_code == 201
    await _login(client, "admin@example.com")
    assert (await client.get("/api/v1/tasks")).json()["items"] == []
    await client.patch(f"/api/v1/admin/users/{users['member@example.com']['id']}", json={"role": "admin"})

    await _login(client, "member@example.com")
    async with user_session(users["member@example.com"]["id"]) as session:
        from app.services import audit

        member_user = await session.get(User, users["member@example.com"]["id"])
        assert await audit.list_entries(session, member_user) == []


async def test_admin_actions_on_modules_and_invitations_are_audited(
    client: httpx.AsyncClient, owner_engine
) -> None:
    await _setup(client)
    await client.put("/api/v1/admin/modules/files", json={"enabled": False})
    created = (await client.post("/api/v1/invitations", json={})).json()
    await client.delete(f"/api/v1/invitations/{created['id']}")
    assert (await _audit(owner_engine, "admin.module.set"))[0]["details"] == {"enabled": False}
    assert len(await _audit(owner_engine, "admin.invitation.create")) == 1
    assert (await _audit(owner_engine, "admin.invitation.revoke"))[0]["target_id"] == created["id"]
    # The invitation token must never reach the audit trail.
    async with owner_engine.connect() as conn:
        dump = str(list(await conn.execute(text("SELECT details FROM audit_log"))))
    assert created["token"] not in dump
    assert PASSWORD not in dump
