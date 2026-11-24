"""OAuth 2.1 discovery and protocol adapters; policy and persistence live in services.oauth."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_user_scoped_session
from app.auth.client_ip import client_ip
from app.auth.manager import current_active_user
from app.auth.rate_limit import consume_window, get_redis, rate_limit_key
from app.config import get_settings
from app.db.models import User
from app.db.session import system_session
from app.services import oauth

router = APIRouter(tags=["oauth"])


def _oauth_error(error: str) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=400, headers={"Cache-Control": "no-store"})


async def enforce_oauth_rate_limit(request: Request, store: Redis = Depends(get_redis)) -> None:
    settings = get_settings()
    try:
        wait = await consume_window(
            store, rate_limit_key("oauth-ip", client_ip(request), settings),
            settings.auth_rate_limit_attempts, settings.auth_rate_limit_window_seconds,
        )
    except Exception:
        return
    if wait is not None:
        raise HTTPException(status_code=429, detail="RATE_LIMITED", headers={"Retry-After": str(wait)})


class RegisterClient(BaseModel):
    client_name: str = Field(min_length=1, max_length=100)
    redirect_uris: list[str] = Field(min_length=1, max_length=20)


class ConsentRequest(BaseModel):
    client_id: str
    redirect_uri: str
    resource: str
    scope: str
    state: str
    code_challenge: str
    code_challenge_method: str
    approved: bool


class GrantOut(BaseModel):
    id: str
    client_name: str
    resource: str
    scopes: list[str]
    created_at: str
    expires_at: str
    last_used_at: str | None


async def _form(request: Request) -> dict[str, str]:
    try:
        values = await request.form()
        return {key: str(value) for key, value in values.items()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_request") from exc


@router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata() -> dict[str, object]:
    issuer = get_settings().app_url.rstrip("/")
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "revocation_endpoint": f"{issuer}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": sorted(oauth.ALL_SCOPES),
        "revocation_endpoint_auth_methods_supported": ["none"],
        "client_id_metadata_document_supported": False,
        "authorization_response_iss_parameter_supported": True,
    }


@router.get("/.well-known/oauth-protected-resource/mcp")
@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata() -> dict[str, object]:
    issuer = get_settings().app_url.rstrip("/")
    return {
        "resource": f"{issuer}/mcp",
        "authorization_servers": [issuer],
        "scopes_supported": sorted(oauth.ALL_SCOPES),
        "bearer_methods_supported": ["header"],
    }


@router.post("/oauth/register", status_code=201, dependencies=[Depends(enforce_oauth_rate_limit)])
async def register_client(body: RegisterClient) -> dict[str, object]:
    try:
        async with system_session() as session:
            client = await oauth.register_client(session, body.client_name, body.redirect_uris)
            result = {
                "client_id": client.client_id, "client_name": client.client_name,
                "redirect_uris": client.redirect_uris, "client_id_issued_at": int(client.created_at.timestamp()),
                "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            }
            return result
    except oauth.OAuthError as exc:
        return _oauth_error(str(exc))


def _request_args(request: Request) -> dict[str, str]:
    return {key: request.query_params.get(key, "") for key in (
        "client_id", "redirect_uri", "scope", "state", "response_type", "code_challenge",
        "code_challenge_method", "resource",
    )}


async def _validate_request(session: AsyncSession, args: dict[str, str]) -> oauth.AuthorizationRequest:
    try:
        return await oauth.authorization_details(
            session, client_id=args["client_id"], redirect_uri=args["redirect_uri"],
            scope=args["scope"], state=args["state"], code_challenge=args["code_challenge"],
            code_challenge_method=args["code_challenge_method"], resource=args["resource"],
        )
    except oauth.OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/oauth/authorize", dependencies=[Depends(enforce_oauth_rate_limit)])
async def authorize(request: Request) -> Response:
    args = _request_args(request)
    if args["response_type"] != "code":
        return _oauth_error("unsupported_response_type")
    async with system_session() as session:
        await _validate_request(session, args)
    query = urlencode({key: args[key] for key in (
        "client_id", "redirect_uri", "scope", "state", "code_challenge", "code_challenge_method", "resource",
    )})
    return RedirectResponse(f"{get_settings().app_url.rstrip('/')}/oauth/consent?{query}", status_code=303)


@router.get("/oauth/consent/details")
async def consent_details(
    request: Request,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> dict[str, object]:
    details = await _validate_request(session, _request_args(request))
    return {
        "client_name": details.client.client_name,
        "redirect_uri": details.redirect_uri,
        "scopes": list(details.scopes),
    }


@router.post("/oauth/consent", dependencies=[Depends(enforce_oauth_rate_limit)])
async def submit_consent(
    body: ConsentRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> Response:
    args = body.model_dump()
    args["response_type"] = "code"
    details = await _validate_request(session, args)
    code = await oauth.consent(session, user, details, body.approved)
    issuer = get_settings().app_url.rstrip("/")
    if code is None:
        query = urlencode({"error": "access_denied", "state": body.state, "iss": issuer})
    else:
        query = urlencode({"code": code, "state": body.state, "iss": issuer})
    return RedirectResponse(f"{body.redirect_uri}?{query}", status_code=303)


@router.post("/oauth/token", dependencies=[Depends(enforce_oauth_rate_limit)])
async def token(request: Request) -> Response:
    data = await _form(request)
    try:
        if data.get("grant_type") == "authorization_code":
            result = await oauth.exchange_code(
                data.get("code", ""), data.get("client_id", ""), data.get("redirect_uri", ""),
                data.get("resource", ""), data.get("code_verifier", ""),
            )
        elif data.get("grant_type") == "refresh_token":
            result = await oauth.refresh_grant(
                data.get("refresh_token", ""), data.get("client_id", ""),
                data.get("resource", ""), data.get("scope")
            )
        else:
            raise oauth.OAuthError("unsupported_grant_type")
    except oauth.OAuthError as exc:
        return _oauth_error(str(exc))
    return JSONResponse(
        result,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.post("/oauth/revoke", dependencies=[Depends(enforce_oauth_rate_limit)])
async def revoke(request: Request) -> Response:
    data = await _form(request)
    await oauth.revoke_credential(data.get("token", ""))
    return Response(status_code=200)


@router.get("/api/v1/oauth/grants", response_model=list[GrantOut])
async def get_grants(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[GrantOut]:
    return [GrantOut(id=grant.id, client_name=name, resource=grant.resource, scopes=grant.scopes,
                     created_at=grant.created_at.isoformat(), expires_at=grant.refresh_expires_at.isoformat(),
                     last_used_at=grant.last_used_at.isoformat() if grant.last_used_at else None)
            for grant, name in await oauth.list_grants(session, user)]


@router.delete("/api/v1/oauth/grants/{grant_id}", status_code=204)
async def delete_grant(
    grant_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> Response:
    if not await oauth.revoke_grant(session, user, grant_id):
        raise HTTPException(status_code=404, detail="OAUTH_GRANT_NOT_FOUND")
    return Response(status_code=204)
