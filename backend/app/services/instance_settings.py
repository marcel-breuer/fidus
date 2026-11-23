"""Instance-wide settings that override environment defaults at runtime."""

from typing import get_args

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import RegistrationMode, get_settings
from app.db.models import InstanceSetting, User
from app.services import audit

_REGISTRATION_KEY = "registration_mode"
_MODES: tuple[str, ...] = get_args(RegistrationMode)


class InvalidRegistrationModeError(ValueError):
    """Raised for a registration mode outside open, invite-only and closed."""


async def get_registration_mode(session: AsyncSession) -> RegistrationMode:
    """The admin-set mode when one exists, otherwise the REGISTRATION_MODE default."""
    row = await session.get(InstanceSetting, _REGISTRATION_KEY)
    if row is not None and row.value in _MODES:
        return row.value  # type: ignore[return-value]
    return get_settings().registration_mode


async def has_registration_override(session: AsyncSession) -> bool:
    return await session.get(InstanceSetting, _REGISTRATION_KEY) is not None


async def set_registration_mode(
    session: AsyncSession, admin: User, mode: str
) -> RegistrationMode:
    if not admin.is_superuser:
        raise PermissionError("ADMIN_REQUIRED")
    if mode not in _MODES:
        raise InvalidRegistrationModeError(mode)
    previous = await get_registration_mode(session)
    row = await session.get(InstanceSetting, _REGISTRATION_KEY)
    if row is None:
        session.add(InstanceSetting(key=_REGISTRATION_KEY, value=mode, updated_by=admin.id))
    else:
        row.value = mode
        row.updated_by = admin.id
    await audit.record(
        session, admin, "admin.registration_mode.set", "instance_setting", None,
        {"from": previous, "to": mode}, actor="admin",
    )
    return mode  # type: ignore[return-value]
