from sqlalchemy import text

from app.db.models import User
from app.db.session import system_session, user_session
from app.services.conversations import (
    add_message,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    list_messages,
    rename_conversation,
    search_messages,
)


async def _users(owner_engine) -> tuple[str, str]:
    ids = ("01HAAAAAAAAAAAAAAAAAAAAAAA", "01HBBBBBBBBBBBBBBBBBBBBBBB")
    async with owner_engine.begin() as connection:
        for index, user_id in enumerate(ids):
            await connection.execute(
                text("INSERT INTO users (id,email,hashed_password,is_active,is_superuser,is_verified) "
                     "VALUES (:id,:email,'x',true,false,false)"),
                {"id": user_id, "email": f"chat-{index}@example.com"},
            )
    await owner_engine.dispose()
    return ids


async def _user(session, user_id: str) -> User:
    user = await session.get(User, user_id)
    assert user is not None
    return user


async def test_conversation_lifecycle_and_cursor_pages(owner_engine) -> None:
    user_a, _ = await _users(owner_engine)
    async with user_session(user_a) as session:
        user = await _user(session, user_a)
        first = await create_conversation(session, user)
        second = await create_conversation(session, user, "Second")
        assert first.title == "New conversation"
        page, cursor = await list_conversations(session, user, limit=1)
        assert len(page) == 1 and cursor
        page_two, no_cursor = await list_conversations(session, user, cursor=cursor, limit=1)
        assert [page[0].id, page_two[0].id] == [second.id, first.id]
        assert no_cursor is None

        one = await add_message(session, user, first.id, "user", "alpha search phrase")
        two = await add_message(session, user, first.id, "assistant", "beta response")
        assert one and two
        messages, message_cursor = await list_messages(session, user, first.id, limit=1)
        next_page, end_cursor = await list_messages(session, user, first.id, cursor=message_cursor, limit=1)
        assert [messages[0].id, next_page[0].id] == [one.id, two.id]
        assert message_cursor and end_cursor is None

        renamed = await rename_conversation(session, user, first.id, "Renamed")
        assert renamed and renamed.title == "Renamed"
        matches = await search_messages(session, user, "alpha search")
        assert [match["message_id"] for match in matches] == [one.id]
        assert await delete_conversation(session, user, first.id)
        assert await get_conversation(session, user, first.id) is None
        assert await list_messages(session, user, first.id) == ([], None)
        assert await search_messages(session, user, "alpha search") == []


async def test_cross_user_service_reads_and_writes_are_scoped(owner_engine) -> None:
    user_a, user_b = await _users(owner_engine)
    async with user_session(user_a) as session:
        owner = await _user(session, user_a)
        conversation = await create_conversation(session, owner, "Private")
        message = await add_message(session, owner, conversation.id, "user", "secret needle")
        assert message

    async with user_session(user_b) as session:
        other = await _user(session, user_b)
        assert await list_conversations(session, other) == ([], None)
        assert await get_conversation(session, other, conversation.id) is None
        assert await rename_conversation(session, other, conversation.id, "Changed") is None
        assert not await delete_conversation(session, other, conversation.id)
        assert await list_messages(session, other, conversation.id) == ([], None)
        assert await add_message(session, other, conversation.id, "user", "forged") is None
        assert await search_messages(session, other, "secret needle") == []


async def test_chat_rls_returns_no_rows_without_user_context(owner_engine) -> None:
    user_a, _ = await _users(owner_engine)
    async with user_session(user_a) as session:
        user = await _user(session, user_a)
        conversation = await create_conversation(session, user)
        await add_message(session, user, conversation.id, "user", "mine")
    async with system_session() as session:
        assert (await session.scalars(text("SELECT id FROM conversations"))).all() == []
        assert (await session.scalars(text("SELECT id FROM messages"))).all() == []
