import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db.session import user_session
from app.services import audit
from tests.helpers import login, register


async def _login(client: httpx.AsyncClient, email: str) -> str:
    await register(client, email)  # a repeated sign-in for the same user is fine
    assert (await login(client, email)).status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    return (await client.get("/api/v1/users/me")).json()["id"]


async def test_memory_crud_and_validation(client: httpx.AsyncClient) -> None:
    await _login(client, "memory@example.com")
    created = await client.post("/api/v1/memories", json={"content": "  Prefers metric units  "})
    assert created.status_code == 201
    memory = created.json()
    assert memory["content"] == "Prefers metric units" and memory["source"] == "user"

    assert (await client.post("/api/v1/memories", json={"content": "   "})).status_code == 422
    assert (await client.post("/api/v1/memories", json={"content": "x" * 1001})).status_code == 422

    patched = await client.patch(f"/api/v1/memories/{memory['id']}", json={"content": "Prefers imperial"})
    assert patched.status_code == 200 and patched.json()["content"] == "Prefers imperial"
    assert [item["content"] for item in (await client.get("/api/v1/memories")).json()] == ["Prefers imperial"]

    assert (await client.delete(f"/api/v1/memories/{memory['id']}")).status_code == 204
    assert (await client.get("/api/v1/memories")).json() == []
    assert (await client.delete(f"/api/v1/memories/{memory['id']}")).status_code == 404


async def test_memories_are_private_to_their_owner(client: httpx.AsyncClient) -> None:
    await _login(client, "memory-a@example.com")
    memory_id = (await client.post("/api/v1/memories", json={"content": "A's secret"})).json()["id"]
    await _login(client, "memory-b@example.com")
    assert (await client.get("/api/v1/memories")).json() == []
    assert (await client.patch(f"/api/v1/memories/{memory_id}", json={"content": "hijack"})).status_code == 404
    assert (await client.delete(f"/api/v1/memories/{memory_id}")).status_code == 404
    await _login(client, "memory-a@example.com")
    assert [item["content"] for item in (await client.get("/api/v1/memories")).json()] == ["A's secret"]


async def test_memory_limit_and_auth_and_csrf(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert (await client.get("/api/v1/memories")).status_code == 401
    await _login(client, "limit@example.com")
    monkeypatch.setattr("app.services.memories.MAX_MEMORIES", 1)
    assert (await client.post("/api/v1/memories", json={"content": "one"})).status_code == 201
    second = await client.post("/api/v1/memories", json={"content": "two"})
    assert second.status_code == 409 and second.json()["detail"] == "MEMORY_LIMIT_REACHED"
    client.headers.pop("X-CSRF-Token")
    assert (await client.post("/api/v1/memories", json={"content": "three"})).status_code == 403


async def test_agent_settings_default_ask_and_are_per_user(client: httpx.AsyncClient) -> None:
    await _login(client, "settings-a@example.com")
    assert (await client.get("/api/v1/agent/settings")).json() == {"write_mode": "ask"}
    assert (await client.put("/api/v1/agent/settings", json={"write_mode": "allow"})).json() == {"write_mode": "allow"}
    assert (await client.put("/api/v1/agent/settings", json={"write_mode": "never"})).status_code == 422
    await _login(client, "settings-b@example.com")
    assert (await client.get("/api/v1/agent/settings")).json() == {"write_mode": "ask"}
    await _login(client, "settings-a@example.com")
    assert (await client.get("/api/v1/agent/settings")).json() == {"write_mode": "allow"}


async def test_audit_log_is_user_scoped_and_append_only(client: httpx.AsyncClient) -> None:
    user_a = await _login(client, "audit-a@example.com")
    user_b = (await register(client, "audit-b@example.com")).json()["id"]
    async with user_session(user_a) as session:
        from app.db.models import User

        owner = await session.get(User, user_a)
        assert owner
        entry = await audit.record(session, owner, "agent.remember", "memory", "01HAAAAAAAAAAAAAAAAAAAAAAA")
        entry_id = entry.id
    assert [item["action"] for item in (await client.get("/api/v1/agent/audit")).json()] == ["agent.remember"]

    async with user_session(user_b) as session:
        assert (await session.scalars(text("SELECT id FROM audit_log"))).all() == []
        with pytest.raises((DBAPIError, ProgrammingError)):
            await session.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": entry_id})
    async with user_session(user_a) as session:
        with pytest.raises((DBAPIError, ProgrammingError)):
            await session.execute(text("UPDATE audit_log SET action = 'x' WHERE id = :id"), {"id": entry_id})
    await _login(client, "audit-b@example.com")
    assert (await client.get("/api/v1/agent/audit")).json() == []


async def test_memory_routes_follow_chat_module_policy(client: httpx.AsyncClient, owner_engine) -> None:
    await _login(client, "module@example.com")
    async with owner_engine.begin() as connection:
        await connection.exec_driver_sql(
            "INSERT INTO module_settings (module_key, enabled) VALUES ('chat', false) "
            "ON CONFLICT (module_key) DO UPDATE SET enabled = false"
        )
    assert (await client.get("/api/v1/memories")).status_code == 404
    assert (await client.get("/api/v1/agent/settings")).status_code == 404
    async with owner_engine.begin() as connection:
        await connection.exec_driver_sql("DELETE FROM module_settings WHERE module_key = 'chat'")
