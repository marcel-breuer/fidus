from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import router as admin_router
from app.api.agent import router as agent_router
from app.api.audio import router as audio_router
from app.api.conversations import router as conversations_router
from app.api.deps import get_user_scoped_session
from app.api.files import router as files_router
from app.api.tasks import router as tasks_router
from app.api.tokens import router as tokens_router
from app.api.usage import router as usage_router
from app.auth.manager import (
    COOKIE_NAME,
    auth_backend,
    current_active_user,
    fastapi_users,
)
from app.auth.rate_limit import enforce_auth_rate_limit
from app.auth.schemas import UserCreate, UserRead
from app.config import get_settings
from app.db.models import User
from app.db.session import system_session
from app.modules.registry import ALL_SCOPES, modules_for_scopes
from app.services.invitations import create_invitation, list_invitations, revoke_invitation
from app.services.module_settings import (
    UnknownModuleError,
    enabled_module_keys,
    list_effective_settings,
    set_enabled,
)
from app.services.sessions import revoke_all_sessions

router = APIRouter(prefix="/api/v1")
router.include_router(admin_router)
router.include_router(conversations_router)
router.include_router(agent_router)


class HealthOut(BaseModel):
    status: str
    database: str


class ModuleOut(BaseModel):
    key: str
    name_key: str
    icon: str
    route: str
    scopes: list[str]


class AdminModuleOut(BaseModel):
    key: str
    name_key: str
    enabled: bool


class ModuleSettingUpdate(BaseModel):
    enabled: bool


class InvitationCreate(BaseModel):
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationOut(BaseModel):
    id: str
    expires_at: datetime


class InvitationCreated(InvitationOut):
    token: str


@router.get("/health", response_model=HealthOut, tags=["health"])
async def health() -> HealthOut:
    try:
        async with system_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return HealthOut(status="ok", database="ok")


@router.get("/modules", response_model=list[ModuleOut], tags=["modules"])
async def list_modules(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[ModuleOut]:
    # Session users hold every scope; token scopes narrow this later.
    enabled = await enabled_module_keys(session)
    return [
        ModuleOut(key=m.key, name_key=m.name_key, icon=m.icon, route=m.route, scopes=list(m.scopes))
        for m in modules_for_scopes(ALL_SCOPES)
        if m.key in enabled
    ]


@router.get("/users/me", response_model=UserRead, tags=["users"])
async def read_me(user: User = Depends(current_active_user)) -> User:
    return user


def _require_admin(user: User) -> None:
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="ADMIN_REQUIRED")


@router.get("/admin/modules", response_model=list[AdminModuleOut], tags=["admin"])
async def get_admin_modules(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[AdminModuleOut]:
    _require_admin(user)
    return [
        AdminModuleOut(key=key, name_key=name_key, enabled=enabled)
        for key, name_key, enabled in await list_effective_settings(session)
    ]


@router.put("/admin/modules/{key}", response_model=AdminModuleOut, tags=["admin"])
async def put_admin_module(
    key: str,
    body: ModuleSettingUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> AdminModuleOut:
    _require_admin(user)
    try:
        setting = await set_enabled(session, user, key, body.enabled)
    except UnknownModuleError as exc:
        raise HTTPException(status_code=404, detail="MODULE_NOT_FOUND") from exc
    module = next(module for module in modules_for_scopes(ALL_SCOPES) if module.key == key)
    return AdminModuleOut(key=key, name_key=module.name_key, enabled=setting.enabled)


@router.post("/invitations", response_model=InvitationCreated, status_code=201, tags=["invitations"])
async def post_invitation(
    body: InvitationCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> InvitationCreated:
    _require_admin(user)
    invitation, token = await create_invitation(
        session, user, timedelta(days=body.expires_in_days)
    )
    return InvitationCreated(id=invitation.id, token=token, expires_at=invitation.expires_at)


@router.get("/invitations", response_model=list[InvitationOut], tags=["invitations"])
async def get_invitations(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[InvitationOut]:
    _require_admin(user)
    return [
        InvitationOut(id=item.id, expires_at=item.expires_at)
        for item in await list_invitations(session, user)
    ]


@router.delete("/invitations/{invitation_id}", status_code=204, tags=["invitations"])
async def delete_invitation(
    invitation_id: str,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> Response:
    _require_admin(user)
    if not await revoke_invitation(session, user, invitation_id):
        raise HTTPException(status_code=404, detail="INVITATION_NOT_FOUND")
    return Response(status_code=204)


@router.post("/auth/logout-all", status_code=204, tags=["auth"])
async def logout_all_sessions(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> Response:
    await revoke_all_sessions(session, user.id)
    response = Response(status_code=204)
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=get_settings().cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


router.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(enforce_auth_rate_limit)],
)
router.include_router(tasks_router)
router.include_router(files_router)
router.include_router(tokens_router)
router.include_router(usage_router)
router.include_router(audio_router)
router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(enforce_auth_rate_limit)],
)
