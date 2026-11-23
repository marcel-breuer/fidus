import httpx

from tests.helpers import PASSWORD, login, register


async def test_register_returns_user_with_ulid_id(client: httpx.AsyncClient) -> None:
    response = await register(client, "first@example.com")
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "first@example.com"
    assert len(body["id"]) == 26
    assert "hashed_password" not in body


async def test_first_user_is_admin_and_later_users_are_members(client: httpx.AsyncClient) -> None:
    first = await register(client, "admin@example.com")
    second = await register(client, "member@example.com")
    assert first.json()["role"] == "admin"
    assert second.json()["role"] == "member"
    assert second.json()["is_superuser"] is False


async def test_register_cannot_self_assign_admin(client: httpx.AsyncClient) -> None:
    await register(client, "admin@example.com")
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "sneaky@example.com", "password": PASSWORD, "is_superuser": True},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "member"


async def test_duplicate_email_is_rejected(client: httpx.AsyncClient) -> None:
    await register(client, "dup@example.com")
    response = await register(client, "dup@example.com")
    assert response.status_code == 400


async def test_login_sets_httponly_session_cookie_and_me_works(client: httpx.AsyncClient) -> None:
    await register(client, "user@example.com")
    response = await login(client, "user@example.com")
    assert response.status_code == 204
    cookie = response.headers["set-cookie"].lower()
    assert "fidus_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie

    me = await client.get("/api/v1/users/me")
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"


async def test_login_with_wrong_password_fails(client: httpx.AsyncClient) -> None:
    await register(client, "user@example.com")
    response = await client.post(
        "/api/v1/auth/login", data={"username": "user@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 400
    assert "set-cookie" not in response.headers


async def test_me_requires_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/users/me")).status_code == 401


async def test_logout_clears_session(client: httpx.AsyncClient) -> None:
    await register(client, "user@example.com")
    await login(client, "user@example.com")
    csrf_token = client.cookies.get("fidus_csrf")
    assert csrf_token is not None
    assert (await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf_token})).status_code == 204
    client.cookies.clear()
    assert (await client.get("/api/v1/users/me")).status_code == 401


async def test_open_registration_allows_further_users(client: httpx.AsyncClient, settings) -> None:
    settings.registration_mode = "open"
    await register(client, "a@example.com")
    assert (await register(client, "b@example.com")).status_code == 201


async def test_closed_registration_rejects_after_first_user(client: httpx.AsyncClient, settings) -> None:
    settings.registration_mode = "closed"
    assert (await register(client, "admin@example.com")).status_code == 201
    response = await register(client, "late@example.com")
    assert response.status_code == 403
    assert response.json()["detail"] == "REGISTRATION_CLOSED"


async def test_invite_only_rejects_uninvited_after_first_user(
    client: httpx.AsyncClient, settings
) -> None:
    settings.registration_mode = "invite-only"
    assert (await register(client, "admin@example.com")).status_code == 201
    assert (await register(client, "late@example.com")).status_code == 403


async def test_rejected_registration_creates_no_account(client: httpx.AsyncClient, settings) -> None:
    settings.registration_mode = "closed"
    await register(client, "admin@example.com")
    await register(client, "late@example.com")
    assert (await login(client, "late@example.com")).status_code == 400


async def test_cross_origin_write_is_refused(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "evil@example.com", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


async def test_same_origin_write_is_accepted(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "ok@example.com", "password": PASSWORD},
        headers={"Origin": "http://localhost:8080"},
    )
    assert response.status_code == 201
