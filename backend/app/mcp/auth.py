"""Bearer authentication for the MCP endpoint.

Only personal access tokens authenticate here; session cookies are ignored, which is why the
cookie CSRF check does not apply to this endpoint."""

import logging
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis

from app.auth.client_ip import client_ip
from app.auth.rate_limit import consume_window, get_redis, rate_limit_key
from app.config import get_settings
from app.db.models import User
from app.db.session import system_session
from app.services.api_tokens import authenticate_token

logger = logging.getLogger(__name__)

_CHALLENGE = {"WWW-Authenticate": 'Bearer realm="fidus"'}


@dataclass(frozen=True)
class McpPrincipal:
    user: User
    token_id: str
    scopes: frozenset[str]


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="INVALID_TOKEN", headers=_CHALLENGE)


def _bearer_secret(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def _limit(store: Redis, key: str, limit: int, window: int) -> None:
    try:
        retry_after = await consume_window(store, key, limit, window)
    except Exception:
        logger.warning("MCP rate-limit storage unavailable; allowing request")
        return
    if retry_after is not None:
        raise HTTPException(status_code=429, detail="RATE_LIMITED", headers={"Retry-After": str(retry_after)})


async def current_mcp_principal(request: Request, store: Redis = Depends(get_redis)) -> McpPrincipal:
    settings = get_settings()
    secret = _bearer_secret(request)
    identity = await authenticate_token(secret) if secret else None
    user: User | None = None
    if identity is not None:
        async with system_session() as session:
            user = await session.get(User, identity.user_id)
    if identity is None or user is None or not user.is_active:
        # Failed attempts share the auth limiter so token guessing is throttled per client address.
        await _limit(
            store,
            rate_limit_key("mcp-failed-ip", client_ip(request), settings),
            settings.auth_rate_limit_attempts,
            settings.auth_rate_limit_window_seconds,
        )
        raise _unauthorized()
    await _limit(
        store,
        rate_limit_key("mcp-token", identity.token_id, settings),
        settings.mcp_rate_limit_requests,
        settings.mcp_rate_limit_window_seconds,
    )
    return McpPrincipal(user=user, token_id=identity.token_id, scopes=identity.scopes)
