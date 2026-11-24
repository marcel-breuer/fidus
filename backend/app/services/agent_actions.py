"""Pending agent writes and the user's decision on them."""

import logging
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentAction, User
from app.services import agent_tools, module_settings
from app.storage.base import Storage

logger = logging.getLogger(__name__)


class ActionNotFound(Exception):
    """The action is missing or belongs to another user."""


class ActionNotPending(Exception):
    """The action was already decided."""


async def outcome_context(session: AsyncSession, user: User, conversation_id: str, action_id: str) -> str:
    action = await session.scalar(select(AgentAction).where(
        AgentAction.id == action_id, AgentAction.user_id == user.id,
        AgentAction.conversation_id == conversation_id,
    ))
    if action is None:
        raise ActionNotFound
    if action.status == "pending":
        raise ActionNotPending
    decision = {"approved": "approved", "rejected": "rejected"}.get(action.status, "could not complete")
    return (
        f"The user {decision} the proposed {action.tool} action. Outcome: {action.status}. "
        "Continue the conversation and acknowledge this result."
    )


async def create_pending(
    session: AsyncSession, user: User, conversation_id: str, message_id: str | None,
    tool: str, arguments: dict,
) -> AgentAction:
    action = AgentAction(
        user_id=user.id, conversation_id=conversation_id, message_id=message_id,
        tool=tool, arguments=arguments, status="pending",
    )
    session.add(action)
    await session.flush()
    return action


async def list_for_conversation(session: AsyncSession, user: User, conversation_id: str) -> list[AgentAction]:
    return list((await session.scalars(
        select(AgentAction)
        .where(AgentAction.user_id == user.id, AgentAction.conversation_id == conversation_id)
        .order_by(AgentAction.created_at, AgentAction.id)
    )).all())


async def decide(
    session: AsyncSession, user: User, action_id: str, approve: bool, storage: Storage | None = None
) -> AgentAction:
    """Run (approve) or discard (reject) a pending action. Only the owner can decide, once."""
    action = await session.scalar(
        select(AgentAction)
        .where(AgentAction.id == action_id, AgentAction.user_id == user.id)
        .with_for_update()
    )
    if action is None:
        raise ActionNotFound
    if action.status != "pending":
        raise ActionNotPending
    action.decided_at = datetime.now(UTC)
    if not approve:
        action.status = "rejected"
        await session.flush()
        return action
    action.status = "failed"
    tool = agent_tools.REGISTRY.get(action.tool)
    enabled = await module_settings.enabled_module_keys(session)
    if tool is not None and tool.write and (tool.module is None or tool.module in enabled):
        try:
            arguments = tool.input_model.model_validate(action.arguments)
            # The savepoint keeps a failed tool from discarding the recorded decision.
            async with session.begin_nested():
                context = agent_tools.ToolContext(user=user, session=session, storage=storage)
                await agent_tools.run_tool(context, tool, arguments)
            action.status = "approved"
        except (ValidationError, agent_tools.ToolError):
            pass
        except Exception:
            logger.warning("Agent action %s failed", action.id, exc_info=True)
    await session.flush()
    return action
