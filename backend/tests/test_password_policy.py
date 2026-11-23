import httpx

from app.auth.manager import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH


async def _register(client: httpx.AsyncClient, password: str, email: str = "policy@example.com") -> httpx.Response:
    return await client.post("/api/v1/auth/register", json={"email": email, "password": password})


async def test_short_password_is_rejected(client: httpx.AsyncClient) -> None:
    response = await _register(client, "a" * (MIN_PASSWORD_LENGTH - 1))
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "REGISTER_INVALID_PASSWORD"
    assert response.json()["detail"]["reason"] == "PASSWORD_LENGTH"


async def test_overlong_password_is_rejected(client: httpx.AsyncClient) -> None:
    assert (await _register(client, "a" * (MAX_PASSWORD_LENGTH + 1))).status_code == 400


async def test_boundary_lengths_are_accepted(client: httpx.AsyncClient) -> None:
    assert (await _register(client, "a" * MIN_PASSWORD_LENGTH)).status_code == 201
    assert (await _register(client, "b" * MAX_PASSWORD_LENGTH, "second@example.com")).status_code == 201


async def test_rejected_registration_creates_no_account(client: httpx.AsyncClient) -> None:
    await _register(client, "short")
    login = await client.post("/api/v1/auth/login", data={"username": "policy@example.com", "password": "short"})
    assert login.status_code == 400
