from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModuleSetting, User
from app.modules.registry import REGISTRY


class UnknownModuleError(ValueError):
    """Raised when a setting refers to a module outside the backend registry."""


def _module_keys() -> set[str]:
    return {module.key for module in REGISTRY}


async def list_effective_settings(session: AsyncSession) -> list[tuple[str, str, bool]]:
    rows = await session.scalars(select(ModuleSetting))
    enabled_by_key = {row.module_key: row.enabled for row in rows}
    return [
        (module.key, module.name_key, enabled_by_key.get(module.key, True))
        for module in REGISTRY
    ]


async def set_enabled(
    session: AsyncSession, admin: User, module_key: str, enabled: bool
) -> ModuleSetting:
    if module_key not in _module_keys():
        raise UnknownModuleError(module_key)
    if not admin.is_superuser:
        raise PermissionError("ADMIN_REQUIRED")
    setting = await session.get(ModuleSetting, module_key)
    if setting is None:
        setting = ModuleSetting(module_key=module_key, enabled=enabled, updated_by=admin.id)
        session.add(setting)
    else:
        setting.enabled = enabled
        setting.updated_by = admin.id
    await session.flush()
    return setting


async def enabled_module_keys(session: AsyncSession) -> set[str]:
    rows = await session.scalars(select(ModuleSetting))
    enabled_by_key = {row.module_key: row.enabled for row in rows}
    return {key for key in _module_keys() if enabled_by_key.get(key, True)}
