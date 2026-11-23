import httpx

PASSWORD = "correct-horse-battery"


async def register(client: httpx.AsyncClient, email: str) -> httpx.Response:
    return await client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})


async def login(client: httpx.AsyncClient, email: str) -> httpx.Response:
    return await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
