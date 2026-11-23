import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from redis.asyncio import Redis

from app.api.routes import router
from app.auth.csrf import csrf_middleware
from app.auth.manager import RegistrationClosedError
from app.config import get_settings
from app.db.session import dispose_engine
from app.logging_config import configure_logging, request_id_var, valid_request_id
from app.mcp.router import router as mcp_router

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
HEALTH_ROUTES = {"/health", "/api/v1/health"}
access_log = logging.getLogger("fidus.access")


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.auth_rate_limit_redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        yield
    finally:
        await app.state.auth_rate_limit_redis.aclose()
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Fidus",
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )

    @app.middleware("http")
    async def reject_cross_origin_writes(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        # Keep the Origin check as a defense in depth layer alongside the
        # cookie-session double-submit token check.
        origin = request.headers.get("origin")
        if request.method in UNSAFE_METHODS and origin and origin != _origin(get_settings().app_url):
            return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
        return await csrf_middleware(request, call_next)

    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        # Outermost layer: every request, including refused ones, gets an id and one access line.
        request_id = valid_request_id(request.headers.get("x-request-id")) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            # The route template, never the raw path or query, which may carry ids or search text.
            route = getattr(request.scope.get("route"), "path", "unmatched")
            # Healthchecks fire every few seconds and would drown the useful lines.
            if route not in HEALTH_ROUTES:
                access_log.info("request", extra={
                    "method": request.method,
                    "route": route,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                })
            request_id_var.reset(token)

    @app.exception_handler(RegistrationClosedError)
    async def registration_closed(_: Request, __: RegistrationClosedError) -> JSONResponse:
        return JSONResponse({"detail": "REGISTRATION_CLOSED"}, status_code=403)

    @app.get("/health", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    app.include_router(mcp_router)
    return app


configure_logging("backend")
app = create_app()
