"""Admin-only user management and registration mode. Thin adapters over the services."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_user_scoped_session
from app.auth.manager import current_active_user
from app.config import RegistrationMode, get_settings
from app.db.models import User
from app.services import admin_users, instance_settings

router = APIRouter(prefix="/admin", tags=["admin"])


async def current_admin(user: User = Depends(current_active_user)) -> User:
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="ADMIN_REQUIRED")
    return user


class AdminUserOut(BaseModel):
    id: str
    email: str
    role: Literal["admin", "member"]
    is_active: bool
    created_at: datetime


class AdminUserUpdate(BaseModel):
    is_active: bool | None = None
    role: Literal["admin", "member"] | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "AdminUserUpdate":
        if self.is_active is None and self.role is None:
            raise ValueError("is_active or role is required")
        return self


class RegistrationOut(BaseModel):
    mode: RegistrationMode
    default: RegistrationMode
    overridden: bool


class RegistrationUpdate(BaseModel):
    mode: RegistrationMode


def _user_out(user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id, email=user.email, role="admin" if user.is_superuser else "member",
        is_active=user.is_active, created_at=user.created_at,
    )


async def _registration_out(session: AsyncSession) -> RegistrationOut:
    return RegistrationOut(
        mode=await instance_settings.get_registration_mode(session),
        default=get_settings().registration_mode,
        overridden=await instance_settings.has_registration_override(session),
    )


@router.get("/users", response_model=list[AdminUserOut])
async def get_users(
    admin: User = Depends(current_admin),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> list[AdminUserOut]:
    return [_user_out(user) for user in await admin_users.list_users(session, admin)]


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def patch_user(
    user_id: str,
    body: AdminUserUpdate,
    admin: User = Depends(current_admin),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> AdminUserOut:
    try:
        user = await admin_users.update_user(
            session, admin, user_id,
            is_active=body.is_active,
            is_admin=None if body.role is None else body.role == "admin",
        )
    except admin_users.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="USER_NOT_FOUND") from exc
    except admin_users.SelfLockoutError as exc:
        raise HTTPException(status_code=409, detail="CANNOT_MODIFY_SELF") from exc
    except admin_users.LastAdminError as exc:
        raise HTTPException(status_code=409, detail="LAST_ADMIN_REQUIRED") from exc
    return _user_out(user)


@router.get("/registration", response_model=RegistrationOut)
async def get_registration(
    _admin: User = Depends(current_admin),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> RegistrationOut:
    return await _registration_out(session)


@router.put("/registration", response_model=RegistrationOut)
async def put_registration(
    body: RegistrationUpdate,
    admin: User = Depends(current_admin),
    session: AsyncSession = Depends(get_user_scoped_session),
) -> RegistrationOut:
    await instance_settings.set_registration_mode(session, admin, body.mode)
    return await _registration_out(session)
