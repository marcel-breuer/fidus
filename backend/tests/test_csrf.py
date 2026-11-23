import httpx

from tests.helpers import login, register


async def test_login_sets_csrf_cookie_with_session_cookie_policy(
    client: httpx.AsyncClient, settings
) -> None:
    await register(client, "user@example.com")

    response = await login(client, "user@example.com")

    assert response.status_code == 204
    cookies = response.headers.get_list("set-cookie")
    csrf_cookie = next(cookie for cookie in cookies if cookie.startswith("fidus_csrf="))
    session_cookie = next(cookie for cookie in cookies if cookie.startswith("fidus_session="))
    lowered = csrf_cookie.lower()
    assert "httponly" not in lowered
    assert ("secure" in lowered) == ("secure" in session_cookie.lower())
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    assert f"max-age={settings.session_lifetime_seconds}" in lowered
    assert client.cookies.get("fidus_csrf") != client.cookies.get("fidus_session")


async def test_logout_without_csrf_header_is_rejected(client: httpx.AsyncClient) -> None:
    await register(client, "user@example.com")
    await login(client, "user@example.com")

    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF_FAILED"}


async def test_logout_with_matching_csrf_token_succeeds_and_clears_cookie(
    client: httpx.AsyncClient,
) -> None:
    await register(client, "user@example.com")
    await login(client, "user@example.com")
    csrf_token = client.cookies.get("fidus_csrf")
    assert csrf_token is not None

    response = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf_token})

    assert response.status_code == 204
    csrf_cookie = next(cookie for cookie in response.headers.get_list("set-cookie") if cookie.startswith("fidus_csrf="))
    assert "max-age=0" in csrf_cookie.lower()


async def test_logout_with_wrong_csrf_token_is_rejected(client: httpx.AsyncClient) -> None:
    await register(client, "user@example.com")
    await login(client, "user@example.com")

    response = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong-token"})

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF_FAILED"}


async def test_request_without_session_cookie_is_not_blocked_by_csrf(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 201

    client.cookies.clear()
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code != 403


async def test_login_and_register_are_exempt_with_an_existing_session(
    client: httpx.AsyncClient,
) -> None:
    await register(client, "first@example.com")
    await login(client, "first@example.com")

    registration = await register(client, "second@example.com")
    relogin = await login(client, "first@example.com")

    assert registration.status_code == 201
    assert relogin.status_code == 204
