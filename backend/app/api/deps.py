import logging
from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.manager import current_active_user
from app.db.models import User
from app.db.session import user_session

logger = logging.getLogger(__name__)


async def get_user_scoped_session(user: User = Depends(current_active_user)) -> AsyncIterator[AsyncSession]:
    """Session whose transaction runs with app.user_id set to the authenticated user."""
    session: AsyncSession | None = None
    try:
        async with user_session(user.id) as session:
            yield session
    except BaseException:
        if session is not None:
            pending = session.info.pop("file_storage_cleanup", [])
            for storage, key in pending:
                if await storage.exists(key):
                    await storage.delete(key)
        raise
    else:
        if session is not None:
            session.info.pop("file_storage_cleanup", None)
            callbacks = session.info.pop("after_commit", [])
            for callback in callbacks:
                try:
                    await callback()
                except Exception:
                    logger.warning("Post-commit callback failed", exc_info=True)
