from collections.abc import Callable

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_user_scoped_session
from app.services.module_settings import enabled_module_keys


def require_module(key: str) -> Callable[..., object]:
    """FastAPI dependency that hides routes for disabled or unknown modules."""

    async def guard(session: AsyncSession = Depends(get_user_scoped_session, scope="function")) -> None:
        if key not in await enabled_module_keys(session):
            raise HTTPException(status_code=404, detail="MODULE_DISABLED")

    return guard
