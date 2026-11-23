import httpx
from fastapi import Depends, FastAPI
from sqlalchemy import text

from app.modules.guard import require_module
from tests.helpers import login, register


async def _login(client: httpx.AsyncClient, email: str) -> None:
    response = await login(client, email)
    assert response.status_code in (200, 204)
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""


async def _create_admin(client: httpx.AsyncClient) -> None:
    response = await register(client, "admin@example.com")
    assert response.status_code == 201
    await _login(client, "admin@example.com")


async def test_module_settings_default_enabled_disable_reenable_and_admin_access(
    client: httpx.AsyncClient,
) -> None:
    await _create_admin(client)
    assert [module["key"] for module in (await client.get("/api/v1/admin/modules")).json()] == [
        "chat", "files", "tasks"
    ]
    initial = await client.get("/api/v1/modules")
    assert [module["key"] for module in initial.json()] == ["chat", "files", "tasks"]

    disabled = await client.put("/api/v1/admin/modules/files", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json() == {"key": "files", "name_key": "modules.files", "enabled": False}
    assert [module["key"] for module in (await client.get("/api/v1/modules")).json()] == [
        "chat", "tasks"
    ]

    member = await register(client, "member@example.com")
    assert member.status_code == 201
    await _login(client, "member@example.com")
    assert [module["key"] for module in (await client.get("/api/v1/modules")).json()] == [
        "chat", "tasks"
    ]
    assert (await client.get("/api/v1/admin/modules")).status_code == 403
    assert (await client.put("/api/v1/admin/modules/files", json={"enabled": True})).status_code == 403

    await _login(client, "admin@example.com")
    enabled = await client.put("/api/v1/admin/modules/files", json={"enabled": True})
    assert enabled.status_code == 200
    assert [module["key"] for module in (await client.get("/api/v1/modules")).json()] == [
        "chat", "files", "tasks"
    ]


async def test_module_admin_endpoints_require_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/admin/modules")).status_code == 401
    assert (await client.put("/api/v1/admin/modules/tasks", json={"enabled": False})).status_code == 401


async def test_unknown_module_and_invalid_request_are_rejected(client: httpx.AsyncClient) -> None:
    await _create_admin(client)
    unknown = await client.put("/api/v1/admin/modules/not-a-module", json={"enabled": False})
    assert unknown.status_code == 404
    malformed = await client.put("/api/v1/admin/modules/tasks", json={"enabled": "maybe"})
    assert malformed.status_code == 422


async def test_disabling_module_does_not_delete_its_data(
    client: httpx.AsyncClient, owner_engine
) -> None:
    await _create_admin(client)
    async with owner_engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO tasks (id, user_id, title) SELECT :id, id, 'kept' FROM users WHERE email = :email"),
            {"id": "01J00000000000000000000001", "email": "admin@example.com"},
        )
    response = await client.put("/api/v1/admin/modules/tasks", json={"enabled": False})
    assert response.status_code == 200
    async with owner_engine.connect() as connection:
        count = await connection.scalar(text("SELECT count(*) FROM tasks"))
    assert count == 1


async def test_module_guard_hides_disabled_module(client: httpx.AsyncClient) -> None:
    await _create_admin(client)
    response = await client.put("/api/v1/admin/modules/tasks", json={"enabled": False})
    assert response.status_code == 200

    app = FastAPI()

    @app.get("/guarded", dependencies=[Depends(require_module("tasks"))])
    async def guarded() -> dict[str, bool]:
        return {"ok": True}

    guarded_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=client.cookies
    )
    async with guarded_client:
        hidden = await guarded_client.get("/guarded")
    assert hidden.status_code == 404
    assert hidden.json() == {"detail": "MODULE_DISABLED"}
