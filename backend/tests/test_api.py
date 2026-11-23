import httpx

from tests.helpers import login, register


async def test_liveness(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_api_health_checks_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_modules_require_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/modules")).status_code == 401


async def test_modules_list_for_authenticated_user(client: httpx.AsyncClient) -> None:
    await register(client, "user@example.com")
    await login(client, "user@example.com")
    response = await client.get("/api/v1/modules")
    assert response.status_code == 200
    modules = response.json()
    assert [m["key"] for m in modules] == ["chat", "files", "tasks"]
    assert modules[0]["name_key"] == "modules.chat"
    assert all({"icon", "route", "scopes"} <= m.keys() for m in modules)


async def test_modules_do_not_depend_unconditionally_on_each_other() -> None:
    from app.modules.registry import REGISTRY, modules_for_scopes

    assert [m.key for m in modules_for_scopes(frozenset({"files:read", "files:write"}))] == ["files"]
    assert all(m.key not in m.optional_with for m in REGISTRY)
