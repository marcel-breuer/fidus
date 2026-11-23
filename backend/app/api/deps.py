from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.manager import current_active_user
from app.db.models import User
from app.db.session import user_session


async def get_user_scoped_session(user: User = Depends(current_active_user)) -> AsyncIterator[AsyncSession]:
    """Session whose transaction runs with app.user_id set to the authenticated user."""
    async with user_session(user.id) as session:
        yield session
