import json
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.ai.fakes import FakeChatProvider
from app.ai.providers import Completed, TextDelta, Usage
from app.db.models import Conversation, Message, User
from app.db.session import user_session
from app.services import chat
from app.services.conversations import add_message, create_conversation
from tests.helpers import login, register


async def _login(client: httpx.AsyncClient, email: str) -> None:
    response = await login(client, email)
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""


async def _conversation(client: httpx.AsyncClient) -> str:
    response = await client.post("/api/v1/conversations", json={})
    assert response.status_code == 201
    return response.json()["id"]


def _events(body: str) -> list[tuple[str, dict[str, object]]]:
    result = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        name = next(line[7:] for line in lines if line.startswith("event: "))
        data = "\n".join(line[6:] for line in lines if line.startswith("data: "))
        result.append((name, json.loads(data)))
    return result


async def test_chat_turn_persists_messages_usage_history_and_title(
    client: httpx.AsyncClient, chat_provider: FakeChatProvider
) -> None:
    user_data = (await register(client, "chat@example.com")).json()
    await _login(client, "chat@example.com")
    conversation_id = await _conversation(client)
    async with user_session(user_data["id"]) as session:
        user = await session.get(User, user_data["id"])
        assert user
        earlier_question = await add_message(session, user, conversation_id, "user", "Earlier question")
        earlier_answer = await add_message(session, user, conversation_id, "assistant", "Earlier answer")
        assert earlier_question and earlier_answer
        earlier_question.created_at = datetime(2025, 1, 1, tzinfo=UTC)
        earlier_answer.created_at = datetime(2025, 1, 1, 0, 0, 1, tzinfo=UTC)

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages/stream",
        json={"content": "  Help me   plan this  "},
    )
    assert response.status_code == 200
    parsed = _events(response.text)
    assert [event for event, _ in parsed] == ["message", "delta", "done"]
    assert parsed[0][1]["content"] == "  Help me   plan this  "
    assert parsed[1][1] == {"text": "Hello"}
    assert parsed[2][1]["title"] == "Help me plan this"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    async with user_session(user_data["id"]) as session:
        rows = list(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at, Message.id)
                )
            ).all()
        )
        conversation = await session.get(Conversation, conversation_id)
    assert [(row.role, row.content) for row in rows] == [
        ("user", "Earlier question"),
        ("assistant", "Earlier answer"),
        ("user", "  Help me   plan this  "),
        ("assistant", "Hello"),
    ]
    assert (rows[3].input_tokens, rows[3].output_tokens) == (4, 2)
    assert conversation and conversation.title == "Help me plan this"
    request = chat_provider.requests[-1]
    assert request.system and "helpful personal assistant" in request.system
    assert [(item.role, item.content) for item in request.messages] == [
        ("user", "Earlier question"),
        ("assistant", "Earlier answer"),
        ("user", "  Help me   plan this  "),
    ]
    assert request.tools == []


async def test_chat_history_budget_keeps_newest_messages(client: httpx.AsyncClient) -> None:
    user_data = (await register(client, "budget@example.com")).json()
    async with user_session(user_data["id"]) as session:
        user = await session.get(User, user_data["id"])
        assert user
        conversation = await create_conversation(session, user)
        oldest = await add_message(session, user, conversation.id, "user", "x" * chat.HISTORY_CHARACTER_BUDGET)
        prior = await add_message(session, user, conversation.id, "assistant", "old")
        assert oldest and prior
        oldest.created_at = datetime(2025, 1, 1, tzinfo=UTC)
        prior.created_at = datetime(2025, 1, 1, 0, 0, 1, tzinfo=UTC)
        conversation_id = conversation.id
    provider = FakeChatProvider([TextDelta("ok"), Completed(Usage(1, 1))])
    async with user_session(user_data["id"]) as session:
        user = await session.get(User, user_data["id"])
    assert user
    events = [
        event
        async for event in chat.run_chat_turn(
            user, conversation_id, "newest", provider, now=datetime(2026, 1, 1, tzinfo=UTC)
        )
    ]
    assert isinstance(events[-1], chat.Done)
    assert [(item.role, item.content) for item in provider.requests[0].messages] == [
        ("assistant", "old"),
        ("user", "newest"),
    ]


async def test_provider_error_keeps_only_user_message(
    client: httpx.AsyncClient, chat_provider: FakeChatProvider
) -> None:
    chat_provider.replies = (TextDelta("partial"), RuntimeError("private provider detail"))  # type: ignore[assignment]
    await register(client, "error@example.com")
    await _login(client, "error@example.com")
    conversation_id = await _conversation(client)
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages/stream", json={"content": "Question"}
    )
    assert [event for event, _ in _events(response.text)] == ["message", "delta", "error"]
    assert "private provider detail" not in response.text
    assert _events(response.text)[-1] == ("error", {"code": "PROVIDER_ERROR"})
    page = await client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert [item["role"] for item in page.json()["items"]] == ["user"]


async def test_closing_stream_after_delta_does_not_store_partial_assistant(
    client: httpx.AsyncClient,
) -> None:
    user_data = (await register(client, "cancel@example.com")).json()
    await _login(client, "cancel@example.com")
    conversation_id = await _conversation(client)
    async with user_session(user_data["id"]) as session:
        user = await session.get(User, user_data["id"])
    assert user
    provider = FakeChatProvider([TextDelta("partial"), Completed(Usage(1, 1))])
    events = chat.run_chat_turn(user, conversation_id, "Question", provider)
    assert isinstance(await events.__anext__(), chat.UserMessageStored)
    assert isinstance(await events.__anext__(), chat.Delta)
    await events.aclose()
    async with user_session(user_data["id"]) as session:
        rows = list((await session.scalars(select(Message).where(Message.conversation_id == conversation_id))).all())
    assert [row.role for row in rows] == ["user"]


async def test_chat_endpoint_auth_csrf_validation_module_and_user_scope(
    client: httpx.AsyncClient, owner_engine
) -> None:
    assert (
        await client.post("/api/v1/conversations/unknown/messages/stream", json={"content": "x"})
    ).status_code == 401
    await register(client, "chat-owner@example.com")
    await register(client, "chat-other@example.com")
    await _login(client, "chat-owner@example.com")
    owned_id = await _conversation(client)
    assert (
        await client.post(f"/api/v1/conversations/{owned_id}/messages/stream", json={"content": ""})
    ).status_code == 422
    assert (
        await client.post(f"/api/v1/conversations/{owned_id}/messages/stream", json={"content": "x" * 20_001})
    ).status_code == 422
    client.headers.pop("X-CSRF-Token")
    assert (
        await client.post(f"/api/v1/conversations/{owned_id}/messages/stream", json={"content": "x"})
    ).status_code == 403
    await _login(client, "chat-other@example.com")
    assert (
        await client.post(f"/api/v1/conversations/{owned_id}/messages/stream", json={"content": "x"})
    ).status_code == 404
    async with owner_engine.begin() as connection:
        await connection.exec_driver_sql(
            "INSERT INTO module_settings (module_key, enabled) VALUES ('chat', false) "
            "ON CONFLICT (module_key) DO UPDATE SET enabled = false"
        )
    assert (
        await client.post(f"/api/v1/conversations/{owned_id}/messages/stream", json={"content": "x"})
    ).status_code == 404
    async with owner_engine.begin() as connection:
        await connection.exec_driver_sql("DELETE FROM module_settings WHERE module_key = 'chat'")
