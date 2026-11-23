from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.ai.prompts import CHAT_SYSTEM_PROMPT
from app.ai.providers import ChatMessage, ChatProvider, ChatRequest, Completed, TextDelta, ToolCall
from app.db.models import Message, User
from app.db.session import user_session
from app.services import conversations

HISTORY_CHARACTER_BUDGET = 24_000


class NotFound(Exception):
    """The conversation is missing or does not belong to the user."""


@dataclass(frozen=True)
class UserMessageStored:
    id: str
    conversation_id: str
    content: str
    created_at: datetime


@dataclass(frozen=True)
class Delta:
    text: str


@dataclass(frozen=True)
class Done:
    message_id: str
    title: str


@dataclass(frozen=True)
class Error:
    code: str = "PROVIDER_ERROR"


type ChatStreamEvent = UserMessageStored | Delta | Done | Error


async def build_context(messages: list[Message]) -> tuple[str, list[ChatMessage]]:
    """Build the model context; retrieval and durable memory can be added here."""
    selected: list[Message] = []
    used = 0
    for message in reversed(messages):
        if used + len(message.content) > HISTORY_CHARACTER_BUDGET:
            break
        selected.append(message)
        used += len(message.content)
    selected.reverse()
    return CHAT_SYSTEM_PROMPT, [ChatMessage(role=item.role, content=item.content) for item in selected]


async def run_chat_turn(
    user: User,
    conversation_id: str,
    user_text: str,
    provider: ChatProvider,
    now: datetime | None = None,
) -> AsyncIterator[ChatStreamEvent]:
    current_time = now or datetime.now(UTC)
    normalized_title = " ".join(user_text.split())[:60]

    async with user_session(user.id) as session:
        conversation = await conversations.get_conversation(session, user, conversation_id)
        if conversation is None:
            raise NotFound
        stored = await conversations.add_message(
            session, user, conversation_id, "user", user_text
        )
        assert stored is not None
        if conversation.title == conversations.DEFAULT_TITLE:
            conversation.title = normalized_title or conversations.DEFAULT_TITLE
        conversation.updated_at = current_time
        await session.flush()
        user_message = UserMessageStored(
            id=stored.id,
            conversation_id=stored.conversation_id,
            content=stored.content,
            created_at=stored.created_at,
        )

    yield user_message

    async with user_session(user.id) as session:
        rows = list((await session.scalars(
            select(Message).where(
                Message.user_id == user.id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            ).order_by(Message.created_at, Message.id)
        )).all())
    system, history = await build_context(rows)
    request = ChatRequest(system=system, messages=history, tools=[])

    answer: list[str] = []
    usage: Completed | None = None
    try:
        async for event in provider.stream(request):
            if isinstance(event, TextDelta):
                answer.append(event.text)
                yield Delta(event.text)
            elif isinstance(event, Completed):
                usage = event
            elif isinstance(event, ToolCall):
                raise RuntimeError("Tool calls are not enabled")
        if usage is None:
            raise RuntimeError("Provider stream did not complete")
    except Exception:
        yield Error()
        return

    missing = False
    assistant_id = ""
    title = ""
    async with user_session(user.id) as session:
        conversation = await conversations.get_conversation(session, user, conversation_id)
        if conversation is None:
            missing = True
        else:
            assistant = await conversations.add_message(
                session,
                user,
                conversation_id,
                "assistant",
                "".join(answer),
                input_tokens=usage.usage.input_tokens,
                output_tokens=usage.usage.output_tokens,
            )
            assert assistant is not None
            conversation.updated_at = current_time
            title = conversation.title
            assistant_id = assistant.id
    if missing:
        yield Error()
        return
    yield Done(message_id=assistant_id, title=title)
