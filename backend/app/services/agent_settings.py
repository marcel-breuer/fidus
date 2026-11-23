"""Per-user agent policy."""

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentSetting, User

type WriteMode = Literal["ask", "allow"]


async def get_write_mode(session: AsyncSession, user: User) -> WriteMode:
    setting = await session.get(AgentSetting, user.id)
    return "allow" if setting is not None and setting.write_mode == "allow" else "ask"


async def set_write_mode(session: AsyncSession, user: User, mode: WriteMode) -> WriteMode:
    setting = await session.get(AgentSetting, user.id)
    if setting is None:
        session.add(AgentSetting(user_id=user.id, write_mode=mode))
    else:
        setting.write_mode = mode
    await session.flush()
    return mode
