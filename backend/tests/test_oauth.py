import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
from sqlalchemy import select

from app.db.models import AuditLog, OAuthAuthorizationCode, OAuthGrant
from app.db.session import user_session
from app.services import api_tokens, oauth
from tests.helpers import PASSWORD, register


async def _login(client: httpx.AsyncClient, email: str) -> str:
    created = await register(client, email)
    assert created.status_code == 201
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    return created.json()["id"]


async def _client(client: httpx.AsyncClient, redirect_uri: str = "http://localhost:54321/callback") -> str:
    response = await client.post(
        "/oauth/register", json={"client_name": "Research Client", "redirect_uris": [redirect_uri]}
    )
    assert response.status_code == 201
    return response.json()["client_id"]


async def _authorize(client: httpx.AsyncClient, client_id: str, scopes: str = "tasks:read") -> tuple[str, str]:
    verifier = "a" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = {
        "response_type": "code", "client_id": client_id,
        "redirect_uri": "http://localhost:54321/callback", "scope": scopes,
        "state": "state-123", "code_challenge": challenge, "code_challenge_method": "S256",
        "resource": "http://localhost:8080/mcp",
    }
    response = await client.get("/oauth/authorize", params=query, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("http://localhost:8080/oauth/consent?")
    details = await client.get("/oauth/consent/details", params=query)
    assert details.status_code == 200
    assert details.json() == {
        "client_name": "Research Client", "redirect_uri": "http://localhost:54321/callback",
        "scopes": scopes.split(),
    }
    consent = await client.post("/oauth/consent", json={**query, "approved": True})
    assert consent.status_code == 303
    callback = parse_qs(urlsplit(consent.headers["location"]).query)
    assert callback["state"] == ["state-123"]
    assert callback["iss"] == ["http://localhost:8080"]
    return callback["code"][0], verifier


async def _exchange(client: httpx.AsyncClient, client_id: str, code: str, verifier: str) -> httpx.Response:
    return await client.post(
        "/oauth/token", data={"grant_type": "authorization_code", "client_id": client_id,
                              "redirect_uri": "http://localhost:54321/callback", "code": code,
                              "resource": "http://localhost:8080/mcp",
                              "code_verifier": verifier}
    )


async def test_oauth_discovery_metadata_is_mcp_compatible(client: httpx.AsyncClient) -> None:
    as_metadata = (await client.get("/.well-known/oauth-authorization-server")).json()
    resource = (await client.get("/.well-known/oauth-protected-resource/mcp")).json()
    assert (await client.get("/.well-known/oauth-protected-resource")).json() == resource
    assert as_metadata["authorization_endpoint"] == "http://localhost:8080/oauth/authorize"
    assert as_metadata["code_challenge_methods_supported"] == ["S256"]
    assert as_metadata["token_endpoint_auth_methods_supported"] == ["none"]
    assert as_metadata["authorization_response_iss_parameter_supported"] is True
    assert resource["resource"] == "http://localhost:8080/mcp"
    assert resource["authorization_servers"] == ["http://localhost:8080"]


async def test_code_exchange_requires_pkce_is_single_use_and_mints_hashed_tokens(
    client: httpx.AsyncClient,
) -> None:
    user_id = await _login(client, "oauth-flow@example.com")
    client_id = await _client(client)
    code, verifier = await _authorize(client, client_id)

    wrong = await _exchange(client, client_id, code, "b" * 64)
    assert wrong.status_code == 400 and wrong.json()["error"] == "invalid_grant"
    response = await _exchange(client, client_id, code, verifier)
    assert response.status_code == 200
    tokens = response.json()
    assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == oauth.ACCESS_TOKEN_SECONDS
    assert tokens["scope"] == "tasks:read"
    assert await api_tokens.authenticate_token(tokens["access_token"]) is not None
    assert await api_tokens.authenticate_token(tokens["access_token"], "https://other.example/mcp") is None
    assert (await _exchange(client, client_id, code, verifier)).status_code == 400

    async with user_session(user_id) as session:
        grant = await session.scalar(select(OAuthGrant))
        audit = list((await session.scalars(select(AuditLog))).all())
    assert grant is not None
    assert grant.access_token_hash == api_tokens.hash_token(tokens["access_token"])
    assert grant.refresh_token_hash == api_tokens.hash_token(tokens["refresh_token"])
    assert tokens["access_token"] not in grant.access_token_hash
    assert {row.action for row in audit} >= {"oauth.authorize", "oauth.token.create"}


async def test_refresh_rotates_tokens_and_rejects_scope_escalation(client: httpx.AsyncClient) -> None:
    await _login(client, "oauth-refresh@example.com")
    client_id = await _client(client)
    code, verifier = await _authorize(client, client_id)
    initial = (await _exchange(client, client_id, code, verifier)).json()

    escalation = await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "client_id": client_id,
        "refresh_token": initial["refresh_token"], "scope": "tasks:write",
        "resource": "http://localhost:8080/mcp",
    })
    assert escalation.status_code == 400 and escalation.json()["error"] == "invalid_scope"

    refreshed = await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "client_id": client_id,
        "refresh_token": initial["refresh_token"], "scope": "tasks:read",
        "resource": "http://localhost:8080/mcp",
    })
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != initial["access_token"]
    old_refresh = await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "client_id": client_id,
        "refresh_token": initial["refresh_token"], "resource": "http://localhost:8080/mcp",
    })
    assert old_refresh.status_code == 400


async def test_revocation_endpoint_stops_access_and_writes_audit(client: httpx.AsyncClient) -> None:
    user_id = await _login(client, "oauth-revoke@example.com")
    client_id = await _client(client)
    code, verifier = await _authorize(client, client_id)
    tokens = (await _exchange(client, client_id, code, verifier)).json()

    revoked = await client.post("/oauth/revoke", data={"token": tokens["refresh_token"]})
    assert revoked.status_code == 200 and revoked.content == b""
    assert await api_tokens.authenticate_token(tokens["access_token"]) is None
    async with user_session(user_id) as session:
        actions = set((await session.scalars(select(AuditLog.action))).all())
    assert "oauth.revoke" in actions


async def test_code_expiry_redirect_validation_and_scope_escalation_are_rejected(
    client: httpx.AsyncClient,
) -> None:
    user_id = await _login(client, "oauth-validation@example.com")
    client_id = await _client(client)
    verifier = "c" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    query = {"response_type": "code", "client_id": client_id,
             "redirect_uri": "http://localhost:54321/callback", "scope": "tasks:read tasks:write",
             "state": "s", "code_challenge": challenge, "code_challenge_method": "S256",
             "resource": "http://localhost:8080/mcp"}
    invalid_redirect = await client.get("/oauth/authorize", params={**query, "redirect_uri": "http://localhost.evil/cb"})
    assert invalid_redirect.status_code == 400
    escalation = await client.get("/oauth/authorize", params={**query, "scope": "admin:all"})
    assert escalation.status_code == 400
    bad_resource = await client.get("/oauth/authorize", params={**query, "resource": "https://other.example/mcp"})
    assert bad_resource.status_code == 400

    raw_code, _ = await _authorize(client, client_id)
    async with user_session(user_id) as session:
        code = await session.scalar(select(OAuthAuthorizationCode))
        assert code is not None
        code.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    expired = await _exchange(client, client_id, raw_code, "a" * 64)
    assert expired.status_code == 400


async def test_user_cannot_list_or_revoke_another_users_oauth_grant(client: httpx.AsyncClient) -> None:
    owner_id = await _login(client, "oauth-owner@example.com")
    client_id = await _client(client)
    code, verifier = await _authorize(client, client_id)
    issued = (await _exchange(client, client_id, code, verifier)).json()
    async with user_session(owner_id) as session:
        grant = await session.scalar(select(OAuthGrant))
        assert grant is not None
        grant_id = grant.id

    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    await _login(client, "oauth-other@example.com")
    assert (await client.get("/api/v1/oauth/grants")).json() == []
    assert (await client.delete(f"/api/v1/oauth/grants/{grant_id}")).status_code == 404
    assert await api_tokens.authenticate_token(issued["access_token"]) is not None


async def test_expired_access_and_refresh_credentials_are_rejected(client: httpx.AsyncClient) -> None:
    user_id = await _login(client, "oauth-expired@example.com")
    client_id = await _client(client)
    access = "fidus_oauth_expired-access"
    refresh = "fidus_refresh_expired-refresh"
    async with user_session(user_id) as session:
        session.add(OAuthGrant(
            user_id=user_id, client_id=client_id, scopes=["tasks:read"],
            resource="http://localhost:8080/mcp",
            access_token_hash=api_tokens.hash_token(access),
            access_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            refresh_token_hash=api_tokens.hash_token(refresh),
            refresh_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        ))
    assert await api_tokens.authenticate_token(access) is None
    response = await client.post("/oauth/token", data={
        "grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh,
        "resource": "http://localhost:8080/mcp",
    })
    assert response.status_code == 400 and response.json()["error"] == "invalid_grant"


async def test_oauth_consent_and_grant_routes_require_cookie_session(client: httpx.AsyncClient) -> None:
    client_id = await _client(client)
    params = {"client_id": client_id, "redirect_uri": "http://localhost:54321/callback",
              "scope": "tasks:read", "state": "state", "code_challenge": "abc",
              "code_challenge_method": "S256", "resource": "http://localhost:8080/mcp"}
    assert (await client.get("/oauth/consent/details", params=params)).status_code == 401
    assert (await client.post("/oauth/consent", json={**params, "approved": True})).status_code == 401
    assert (await client.get("/api/v1/oauth/grants")).status_code == 401
    assert (await client.delete("/api/v1/oauth/grants/missing")).status_code == 401


async def test_dcr_rejects_non_https_non_local_redirects(client: httpx.AsyncClient) -> None:
    bad = await client.post("/oauth/register", json={
        "client_name": "Bad Client", "redirect_uris": ["http://example.com/callback"]
    })
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_redirect_uri"
    https = await client.post("/oauth/register", json={
        "client_name": "HTTPS Client", "redirect_uris": ["https://client.example/callback"]
    })
    assert https.status_code == 201


async def test_dynamic_registration_is_rate_limited(client: httpx.AsyncClient, settings) -> None:
    settings.auth_rate_limit_attempts = 1
    settings.auth_rate_limit_window_seconds = 60
    body = {"client_name": "Limited Client", "redirect_uris": ["https://client.example/callback"]}
    assert (await client.post("/oauth/register", json=body)).status_code == 201
    limited = await client.post("/oauth/register", json=body)
    assert limited.status_code == 429
    assert limited.headers["retry-after"]
