"""Worker-side module enablement check for module jobs to call before processing."""

from app.db.session import system_session
from app.services.module_settings import enabled_module_keys


async def ensure_module_enabled(key: str) -> None:
    """Raise when a module job is no longer enabled for this instance."""
    async with system_session() as session:
        if key not in await enabled_module_keys(session):
            raise RuntimeError("MODULE_DISABLED")
