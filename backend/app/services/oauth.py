"""OAuth 2.1 public-client registration, consent codes and rotating opaque grants."""

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import OAuthAuthorizationCode, OAuthClient, OAuthGrant, User
from app.db.session import set_user_context, system_session
from app.modules.registry import ALL_SCOPES
from app.services import audit
from app.services.api_tokens import hash_token

ACCESS_TOKEN_SECONDS = 900
REFRESH_TOKEN_DAYS = 30
CODE_SECONDS = 300


class OAuthError(ValueError):
    """Safe OAuth protocol error."""


@dataclass(frozen=True)
class AuthorizationRequest:
    client: OAuthClient
    redirect_uri: str
    resource: str
    scopes: tuple[str, ...]
    state: str
    challenge: str


def valid_redirect_uri(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            return False
        if parsed.scheme == "https":
            return True
        return parsed.scheme == "http" and parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        return False


def decode_scopes(scope: str) -> tuple[str, ...]:
    values = tuple(sorted(set(scope.split())))
    if not values or not set(values) <= ALL_SCOPES:
        raise OAuthError("invalid_scope")
    return values


async def register_client(session: AsyncSession, name: str, redirects: list[str]) -> OAuthClient:
    clean_name = name.strip()
    if not clean_name or len(clean_name) > 100 or not 1 <= len(redirects) <= 20:
        raise OAuthError("invalid_client_metadata")
    if len(set(redirects)) != len(redirects) or any(not valid_redirect_uri(uri) for uri in redirects):
        raise OAuthError("invalid_redirect_uri")
    client = OAuthClient(
        client_id=secrets.token_urlsafe(32), client_name=clean_name, redirect_uris=redirects
    )
    session.add(client)
    await session.flush()
    return client


async def validate_authorization(
    session: AsyncSession, client_id: str, redirect_uri: str, scope: str,
    response_type: str, challenge: str, challenge_method: str, resource: str,
) -> AuthorizationRequest:
    client = await session.get(OAuthClient, client_id)
    if client is None:
        raise OAuthError("invalid_client")
    if redirect_uri not in client.redirect_uris or not valid_redirect_uri(redirect_uri):
        raise OAuthError("invalid_redirect_uri")
    if response_type != "code":
        raise OAuthError("unsupported_response_type")
    if challenge_method != "S256" or re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge) is None:
        raise OAuthError("invalid_request")
    expected_resource = f"{get_settings().app_url.rstrip('/')}/mcp"
    if resource != expected_resource:
        raise OAuthError("invalid_target")
    scopes = decode_scopes(scope)
    return AuthorizationRequest(client, redirect_uri, resource, scopes, "", challenge)


async def authorization_details(
    session: AsyncSession, *, client_id: str, redirect_uri: str, scope: str,
    state: str, code_challenge: str, code_challenge_method: str, resource: str,
) -> AuthorizationRequest:
    if len(state) > 512 or not state:
        raise OAuthError("invalid_request")
    request = await validate_authorization(
        session, client_id, redirect_uri, scope, "code", code_challenge, code_challenge_method, resource
    )
    return AuthorizationRequest(
        request.client, request.redirect_uri, request.resource, request.scopes, state, request.challenge
    )


async def consent(
    session: AsyncSession, user: User, request: AuthorizationRequest, approved: bool
) -> str | None:
    if not approved:
        await audit.record(session, user, "oauth.deny", "oauth_client", None,
                           {"client_id": request.client.client_id, "scopes": list(request.scopes)}, actor="user")
        return None
    raw_code = "fidus_code_" + secrets.token_urlsafe(32)
    code = OAuthAuthorizationCode(
        user_id=user.id, client_id=request.client.client_id, code_hash=hash_token(raw_code),
        redirect_uri=request.redirect_uri, resource=request.resource, scopes=list(request.scopes),
        code_challenge=request.challenge, expires_at=datetime.now(UTC) + timedelta(seconds=CODE_SECONDS),
    )
    session.add(code)
    await session.flush()
    await audit.record(session, user, "oauth.authorize", "oauth_client", None,
                       {"client_id": request.client.client_id, "scopes": list(request.scopes)}, actor="user")
    return raw_code


def _new_tokens() -> tuple[str, str]:
    return "fidus_oauth_" + secrets.token_urlsafe(32), "fidus_refresh_" + secrets.token_urlsafe(32)


def _token_response(access: str, refresh: str, scopes: list[str], now: datetime) -> dict[str, object]:
    return {
        "access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TOKEN_SECONDS,
        "refresh_token": refresh, "scope": " ".join(scopes),
    }


async def exchange_code(
    raw_code: str, client_id: str, redirect_uri: str, resource: str, verifier: str,
    *, now: datetime | None = None,
) -> dict[str, object]:
    if (
        not raw_code.startswith("fidus_code_") or not 43 <= len(verifier) <= 128
        or re.fullmatch(r"[A-Za-z0-9._~-]+", verifier) is None
    ):
        raise OAuthError("invalid_grant")
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    async with system_session() as session:
        row = (await session.execute(text("SELECT * FROM oauth_lookup_code(:hash)"),
                                     {"hash": hash_token(raw_code)})).mappings().first()
        if (
            row is None or row["client_id"] != client_id or row["redirect_uri"] != redirect_uri
            or row["resource"] != resource
        ):
            raise OAuthError("invalid_grant")
        if not hmac.compare_digest(row["challenge"], digest):
            raise OAuthError("invalid_grant")
        await set_user_context(session, row["user_id"])
        code = await session.scalar(select(OAuthAuthorizationCode).where(
            OAuthAuthorizationCode.id == row["code_id"], OAuthAuthorizationCode.used_at.is_(None)
        ).with_for_update())
        user = await session.get(User, row["user_id"])
        if code is None or user is None or not user.is_active or code.expires_at <= (now or datetime.now(UTC)):
            raise OAuthError("invalid_grant")
        code.used_at = now or datetime.now(UTC)
        access, refresh = _new_tokens()
        grant = OAuthGrant(
            user_id=user.id, client_id=client_id, resource=resource, scopes=list(row["scopes"]),
            access_token_hash=hash_token(access),
            access_expires_at=(now or datetime.now(UTC)) + timedelta(seconds=ACCESS_TOKEN_SECONDS),
            refresh_token_hash=hash_token(refresh),
            refresh_expires_at=(now or datetime.now(UTC)) + timedelta(days=REFRESH_TOKEN_DAYS),
        )
        session.add(grant)
        await session.flush()
        await audit.record(session, user, "oauth.token.create", "oauth_grant", grant.id,
                           {"client_id": client_id, "scopes": list(grant.scopes)}, actor="oauth")
        return _token_response(access, refresh, grant.scopes, now or datetime.now(UTC))


async def refresh_grant(
    raw_refresh: str, client_id: str, resource: str, requested_scope: str | None = None,
    *, now: datetime | None = None,
) -> dict[str, object]:
    if not raw_refresh.startswith("fidus_refresh_"):
        raise OAuthError("invalid_grant")
    now = now or datetime.now(UTC)
    async with system_session() as session:
        row = (await session.execute(text("SELECT * FROM oauth_lookup_refresh(:hash)"),
                                     {"hash": hash_token(raw_refresh)})).mappings().first()
        if row is None or row["client_id"] != client_id or row["resource"] != resource:
            raise OAuthError("invalid_grant")
        granted = set(row["scopes"])
        scopes = set(decode_scopes(requested_scope)) if requested_scope else granted
        if not scopes <= granted:
            raise OAuthError("invalid_scope")
        await set_user_context(session, row["user_id"])
        grant = await session.scalar(select(OAuthGrant).where(
            OAuthGrant.id == row["grant_id"], OAuthGrant.revoked_at.is_(None)
        ).with_for_update())
        user = await session.get(User, row["user_id"])
        if (
            grant is None or user is None or not user.is_active or grant.refresh_expires_at <= now
            or grant.resource != resource
        ):
            raise OAuthError("invalid_grant")
        if not hmac.compare_digest(grant.refresh_token_hash, hash_token(raw_refresh)):
            raise OAuthError("invalid_grant")
        access, refresh = _new_tokens()
        grant.scopes = sorted(scopes)
        grant.access_token_hash = hash_token(access)
        grant.access_expires_at = now + timedelta(seconds=ACCESS_TOKEN_SECONDS)
        grant.refresh_token_hash = hash_token(refresh)
        grant.refresh_expires_at = now + timedelta(days=REFRESH_TOKEN_DAYS)
        await audit.record(session, user, "oauth.token.refresh", "oauth_grant", grant.id,
                           {"client_id": client_id, "scopes": grant.scopes}, actor="oauth")
        return _token_response(access, refresh, grant.scopes, now)


async def revoke_credential(raw_token: str) -> None:
    if not raw_token or len(raw_token) > 256:
        return
    async with system_session() as session:
        await session.execute(text("SELECT oauth_revoke_token(:hash)"), {"hash": hash_token(raw_token)})


async def list_grants(session: AsyncSession, user: User) -> list[tuple[OAuthGrant, str]]:
    rows = (await session.execute(
        select(OAuthGrant, OAuthClient.client_name).join(OAuthClient, OAuthGrant.client_id == OAuthClient.client_id)
        .where(OAuthGrant.user_id == user.id, OAuthGrant.revoked_at.is_(None))
        .order_by(OAuthGrant.created_at.desc(), OAuthGrant.id.desc())
    )).all()
    return list(rows)


async def revoke_grant(session: AsyncSession, user: User, grant_id: str) -> bool:
    grant = await session.scalar(select(OAuthGrant).where(
        OAuthGrant.id == grant_id, OAuthGrant.user_id == user.id, OAuthGrant.revoked_at.is_(None)
    ))
    if grant is None:
        return False
    grant.revoked_at = datetime.now(UTC)
    await audit.record(session, user, "oauth.revoke", "oauth_grant", grant.id,
                       {"client_id": grant.client_id}, actor="user")
    return True
