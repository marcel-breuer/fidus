import hashlib
import logging
from typing import Protocol

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis

from app.auth.client_ip import client_ip
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class RateLimitStore(Protocol):
    async def eval(self, script: str, numkeys: int, *keys_and_args: str | int) -> list[int]: ...


async def get_redis(request: Request) -> Redis:
    return request.app.state.auth_rate_limit_redis


def _key(scope: str, identifier: str, settings: Settings) -> str:
    digest = hashlib.sha256(f"{settings.secret_key}:{identifier}".encode()).hexdigest()
    return f"fidus:auth-rate-limit:{scope}:{digest}"


async def _consume(store: RateLimitStore, key: str, settings: Settings) -> int | None:
    result = await store.eval(
        "local count = redis.call('INCR', KEYS[1]); "
        "if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]); end; "
        "return {count, redis.call('TTL', KEYS[1])}",
        1,
        key,
        settings.auth_rate_limit_window_seconds,
    )
    attempts, remaining = int(result[0]), int(result[1])
    if attempts <= settings.auth_rate_limit_attempts:
        return None
    return max(1, remaining)


async def enforce_auth_rate_limit(
    request: Request,
    store: Redis = Depends(get_redis),
) -> None:
    path = request.url.path
    if path.endswith("/login"):
        account_field = "username"
    elif path.endswith("/register"):
        account_field = "email"
    else:
        return

    settings = get_settings()
    ip_address = client_ip(request)
    account = ""
    try:
        if account_field == "username":
            form = await request.form()
            account = str(form.get(account_field, "")).strip().casefold()
        else:
            body = await request.json()
            if isinstance(body, dict):
                account = str(body.get(account_field, "")).strip().casefold()
    except (ValueError, TypeError):
        pass

    try:
        retry_after = await _consume(
            store,
            _key("ip", ip_address, settings),
            settings,
        )
        if account:
            account_retry_after = await _consume(
                store,
                _key("account", account, settings),
                settings,
            )
            if account_retry_after is not None:
                retry_after = max(retry_after or 0, account_retry_after)
    except Exception:
        logger.warning("Auth rate-limit storage unavailable; allowing request")
        return

    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="RATE_LIMITED",
            headers={"Retry-After": str(retry_after)},
        )
