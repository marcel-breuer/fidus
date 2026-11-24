import base64
import binascii
import json
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Conversation, Message, User
from app.storage.base import Storage

DEFAULT_TITLE = "New conversation"


def _cursor_encode(timestamp: datetime, row_id: str) -> str:
    payload = json.dumps([timestamp.isoformat(), row_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _cursor_decode(cursor: str | None) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        timestamp = datetime.fromisoformat(value[0])
        if timestamp.tzinfo is None or not isinstance(value[1], str):
            raise ValueError
        return timestamp, value[1]
    except (
        ValueError, TypeError, IndexError, KeyError, json.JSONDecodeError,
        binascii.Error, UnicodeDecodeError,
    ) as exc:
        raise ValueError("Invalid cursor") from exc


async def create_conversation(
    session: AsyncSession, user: User, title: str | None = None
) -> Conversation:
    conversation = Conversation(user_id=user.id, title=title if title is not None else DEFAULT_TITLE)
    session.add(conversation)
    await session.flush()
    return conversation


async def list_conversations(
    session: AsyncSession, user: User, cursor: str | None = None, limit: int = 50
) -> tuple[list[Conversation], str | None]:
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100")
    statement = select(Conversation).where(
        Conversation.user_id == user.id, Conversation.deleted_at.is_(None)
    )
    decoded = _cursor_decode(cursor)
    if decoded:
        timestamp, row_id = decoded
        statement = statement.where(
            or_(Conversation.updated_at < timestamp,
                and_(Conversation.updated_at == timestamp, Conversation.id < row_id))
        )
    rows = list((await session.scalars(
        statement.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit + 1)
    )).all())
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _cursor_encode(rows[-1].updated_at, rows[-1].id) if more and rows else None
    return rows, next_cursor


async def get_conversation(
    session: AsyncSession, user: User, conversation_id: str
) -> Conversation | None:
    return await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
            Conversation.deleted_at.is_(None),
        )
    )


async def rename_conversation(
    session: AsyncSession, user: User, conversation_id: str, title: str
) -> Conversation | None:
    conversation = await get_conversation(session, user, conversation_id)
    if conversation is None:
        return None
    conversation.title = title
    conversation.updated_at = datetime.now(UTC)
    await session.flush()
    return conversation


async def delete_conversation(
    session: AsyncSession, user: User, conversation_id: str, storage: Storage | None = None
) -> bool:
    conversation = await get_conversation(session, user, conversation_id)
    if conversation is None:
        return False
    now = datetime.now(UTC)
    conversation.deleted_at = now
    conversation.updated_at = now
    message_rows = await session.scalars(
        select(Message.speech_key).where(
            Message.conversation_id == conversation_id,
            Message.user_id == user.id,
            Message.speech_key.is_not(None),
        )
    )
    speech_keys = list(message_rows.all())
    await session.execute(
        text(
            "UPDATE messages SET deleted_at = :now WHERE conversation_id = :id "
            "AND user_id = :user_id AND deleted_at IS NULL"
        ),
        {"now": now, "id": conversation_id, "user_id": user.id},
    )
    if storage is not None and speech_keys:
        async def remove_speech() -> None:
            for key in speech_keys:
                await storage.delete(key)

        session.info.setdefault("after_commit", []).append(remove_speech)
    return True


async def add_message(
    session: AsyncSession,
    user: User,
    conversation_id: str,
    role: str,
    content: str,
    *,
    tool_calls: dict | list | None = None,
    citations: dict | list | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> Message | None:
    if role not in {"user", "assistant", "system", "tool"}:
        raise ValueError("Invalid message role")
    conversation = await get_conversation(session, user, conversation_id)
    if conversation is None:
        return None
    message = Message(
        user_id=user.id, conversation_id=conversation.id, role=role, content=content,
        tool_calls=tool_calls, citations=citations, input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    session.add(message)
    conversation.updated_at = datetime.now(UTC)
    await session.flush()
    return message


async def list_messages(
    session: AsyncSession, user: User, conversation_id: str,
    cursor: str | None = None, limit: int = 50,
) -> tuple[list[Message], str | None]:
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100")
    if await get_conversation(session, user, conversation_id) is None:
        return [], None
    statement = select(Message).options(selectinload(Message.attachments)).where(
        Message.user_id == user.id,
        Message.conversation_id == conversation_id,
        Message.deleted_at.is_(None),
    )
    decoded = _cursor_decode(cursor)
    if decoded:
        timestamp, row_id = decoded
        statement = statement.where(tuple_(Message.created_at, Message.id) > tuple_(timestamp, row_id))
    rows = list((await session.scalars(
        statement.order_by(Message.created_at, Message.id).limit(limit + 1)
    )).all())
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _cursor_encode(rows[-1].created_at, rows[-1].id) if more and rows else None
    return rows, next_cursor


async def search_messages(
    session: AsyncSession, user: User, query: str, limit: int = 20
) -> list[dict[str, object]]:
    if not 1 <= limit <= 100:
        raise ValueError("Limit must be between 1 and 100")
    result = await session.execute(
        text("""
            SELECT m.conversation_id, m.id AS message_id,
                   ts_headline('simple', m.content, plainto_tsquery('simple', :q)) AS snippet
            FROM messages AS m
            JOIN conversations AS c ON c.id = m.conversation_id
            WHERE m.user_id = :user_id AND c.user_id = :user_id
              AND m.deleted_at IS NULL AND c.deleted_at IS NULL
              AND m.search @@ plainto_tsquery('simple', :q)
            ORDER BY ts_rank(m.search, plainto_tsquery('simple', :q)) DESC,
                     m.created_at DESC, m.id DESC
            LIMIT :limit
        """),
        {"q": query, "user_id": user.id, "limit": limit},
    )
    return [dict(row) for row in result.mappings().all()]
