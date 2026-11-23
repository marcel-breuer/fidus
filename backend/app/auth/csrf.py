import hmac
import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.auth.manager import COOKIE_NAME
from app.config import get_settings

CSRF_COOKIE_NAME = "fidus_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
_EXEMPT_PATHS = {"/api/v1/auth/login", "/api/v1/auth/register"}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _tokens_match(cookie_token: str | None, header_token: str | None) -> bool:
    if cookie_token is None or header_token is None:
        return False
    return hmac.compare_digest(cookie_token.encode("utf-8"), header_token.encode("utf-8"))


def _set_csrf_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=settings.session_lifetime_seconds,
        path="/",
        secure=settings.cookie_secure,
        httponly=False,
        samesite="lax",
    )


def _clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
        secure=get_settings().cookie_secure,
        httponly=False,
        samesite="lax",
    )


async def csrf_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if (
        request.method in _UNSAFE_METHODS
        and request.url.path not in _EXEMPT_PATHS
        and COOKIE_NAME in request.cookies
        and not _tokens_match(
            request.cookies.get(CSRF_COOKIE_NAME), request.headers.get(CSRF_HEADER_NAME)
        )
    ):
        return JSONResponse({"detail": "CSRF_FAILED"}, status_code=403)

    response = await call_next(request)
    if request.url.path == "/api/v1/auth/login" and response.status_code < 300:
        _set_csrf_cookie(response, secrets.token_urlsafe(32))
    elif request.url.path == "/api/v1/auth/logout" and response.status_code < 300:
        _clear_csrf_cookie(response)
    return response
