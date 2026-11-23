from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.auth.manager import (
    auth_backend,
    current_active_user,
    fastapi_users,
)
from app.auth.rate_limit import enforce_auth_rate_limit
from app.auth.schemas import UserCreate, UserRead
from app.db.models import User
from app.db.session import system_session
from app.modules.registry import ALL_SCOPES, modules_for_scopes

router = APIRouter(prefix="/api/v1")


class HealthOut(BaseModel):
    status: str
    database: str


class ModuleOut(BaseModel):
    key: str
    name_key: str
    icon: str
    route: str
    scopes: list[str]


@router.get("/health", response_model=HealthOut, tags=["health"])
async def health() -> HealthOut:
    try:
        async with system_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return HealthOut(status="ok", database="ok")


@router.get("/modules", response_model=list[ModuleOut], tags=["modules"])
async def list_modules(user: User = Depends(current_active_user)) -> list[ModuleOut]:
    # Session users hold every scope; token scopes narrow this later.
    return [
        ModuleOut(key=m.key, name_key=m.name_key, icon=m.icon, route=m.route, scopes=list(m.scopes))
        for m in modules_for_scopes(ALL_SCOPES)
    ]


@router.get("/users/me", response_model=UserRead, tags=["users"])
async def read_me(user: User = Depends(current_active_user)) -> User:
    return user


router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(enforce_auth_rate_limit)],
)
router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(enforce_auth_rate_limit)],
)
