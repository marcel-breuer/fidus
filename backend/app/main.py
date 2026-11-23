from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.api.routes import router
from app.auth.manager import RegistrationClosedError
from app.config import get_settings
from app.db.session import dispose_engine

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
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
        # Cookie sessions need CSRF protection. Browsers always send Origin on
        # cross-site writes, so a foreign Origin is refused; clients without one
        # (scripts, tests) are not browsers and carry no ambient cookies.
        origin = request.headers.get("origin")
        if request.method in UNSAFE_METHODS and origin and origin != _origin(get_settings().app_url):
            return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(RegistrationClosedError)
    async def registration_closed(_: Request, __: RegistrationClosedError) -> JSONResponse:
        return JSONResponse({"detail": "REGISTRATION_CLOSED"}, status_code=403)

    @app.get("/health", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    return app


app = create_app()
