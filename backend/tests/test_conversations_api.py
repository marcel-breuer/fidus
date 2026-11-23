import httpx
from sqlalchemy import text

from app.db.models import User
from app.db.session import user_session
from app.services.conversations import add_message
from tests.helpers import login, register


async def _login(client: httpx.AsyncClient, email: str) -> None:
    response = await login(client, email)
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""


async def test_conversation_routes_crud_pagination_and_csrf(client: httpx.AsyncClient) -> None:
    assert (await register(client, "owner@example.com")).status_code == 201
    await _login(client, "owner@example.com")
    created = await client.post("/api/v1/conversations", json={})
    assert created.status_code == 201
    first = created.json()
    assert first["title"] == "New conversation"

    second = await client.post("/api/v1/conversations", json={"title": "Second"})
    assert second.status_code == 201
    page = await client.get("/api/v1/conversations?limit=1")
    assert page.status_code == 200 and len(page.json()["items"]) == 1
    next_page = await client.get("/api/v1/conversations", params={"limit": 1, "cursor": page.json()["next_cursor"]})
    assert len(next_page.json()["items"]) == 1

    assert (await client.get(f"/api/v1/conversations/{first['id']}")).status_code == 200
    renamed = await client.patch(f"/api/v1/conversations/{first['id']}", json={"title": "Renamed"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Renamed"
    deleted = await client.delete(f"/api/v1/conversations/{first['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/conversations/{first['id']}")).status_code == 404
    assert (await client.post("/api/v1/conversations", json={})).status_code == 201


async def test_cross_user_routes_and_search_are_isolated(client: httpx.AsyncClient) -> None:
    user_a = (await register(client, "a@example.com")).json()
    assert (await register(client, "b@example.com")).status_code == 201
    await _login(client, "a@example.com")
    created = (await client.post("/api/v1/conversations", json={})).json()
    async with user_session(user_a["id"]) as session:
        user = await session.get(User, user_a["id"])
        assert user
        await add_message(session, user, created["id"], "user", "owner secret needle")

    await _login(client, "b@example.com")
    assert (await client.get("/api/v1/conversations")).json()["items"] == []
    assert (await client.get(f"/api/v1/conversations/{created['id']}")).status_code == 404
    assert (await client.patch(f"/api/v1/conversations/{created['id']}", json={"title": "No"})).status_code == 404
    assert (await client.delete(f"/api/v1/conversations/{created['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/conversations/{created['id']}/messages")).status_code == 404
    assert (await client.get("/api/v1/search/messages?q=secret+needle")).json() == []


async def test_authentication_and_disabled_module(client: httpx.AsyncClient, owner_engine) -> None:
    assert (await client.get("/api/v1/conversations")).status_code == 401
    registered = await register(client, "disabled@example.com")
    await _login(client, "disabled@example.com")
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO module_settings (module_key, enabled) VALUES ('chat', false) "
                 "ON CONFLICT (module_key) DO UPDATE SET enabled = false")
        )
    response = await client.get("/api/v1/conversations")
    assert response.status_code == 404 and response.json() == {"detail": "MODULE_DISABLED"}
    async with owner_engine.begin() as connection:
        await connection.execute(text("DELETE FROM module_settings WHERE module_key = 'chat'"))
    assert registered.status_code == 201
