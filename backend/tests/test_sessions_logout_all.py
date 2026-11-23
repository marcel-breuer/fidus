import httpx
from fastapi import FastAPI

from tests.helpers import login, register


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _login_with_csrf(client: httpx.AsyncClient, email: str) -> None:
    response = await login(client, email)
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""


async def test_logout_all_revokes_only_the_current_users_sessions(
    client: httpx.AsyncClient,
) -> None:
    app = client._transport.app
    await register(client, "session-owner@example.com")
    await _login_with_csrf(client, "session-owner@example.com")

    async with _client(app) as second_session, _client(app) as other_user:
        await _login_with_csrf(second_session, "session-owner@example.com")
        await register(other_user, "other-user@example.com")
        await _login_with_csrf(other_user, "other-user@example.com")

        response = await client.post("/api/v1/auth/logout-all")

        assert response.status_code == 204
        cleared = response.headers.get_list("set-cookie")
        assert any(value.startswith("fidus_session=") and "max-age=0" in value.lower() for value in cleared)
        assert any(value.startswith("fidus_csrf=") and "max-age=0" in value.lower() for value in cleared)
        assert (await client.get("/api/v1/users/me")).status_code == 401
        assert (await second_session.get("/api/v1/users/me")).status_code == 401
        assert (await other_user.get("/api/v1/users/me")).status_code == 200


async def test_logout_all_requires_authentication_and_csrf(
    client: httpx.AsyncClient,
) -> None:
    assert (await client.post("/api/v1/auth/logout-all")).status_code == 401

    await register(client, "csrf-owner@example.com")
    await login(client, "csrf-owner@example.com")

    response = await client.post("/api/v1/auth/logout-all")

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF_FAILED"}

