from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.ai.fakes import FakeEmbeddingProvider, FakeTranscriptionProvider
from app.db.models import Document, UsageRecord, User
from app.db.session import system_session, user_session
from app.services import usage
from app.services.transcription import SEGMENT_BITRATE, process_memo
from app.worker.tasks import process_index_document
from tests.helpers import PASSWORD, register

WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64


async def _login(client: httpx.AsyncClient, email: str) -> str:
    registered = await register(client, email)
    assert registered.status_code == 201
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    return registered.json()["id"]


async def _totals(client: httpx.AsyncClient) -> dict:
    response = await client.get("/api/v1/usage")
    assert response.status_code == 200
    return response.json()["totals"]


async def test_usage_requires_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/usage")).status_code == 401


async def test_empty_usage_is_all_zero(client: httpx.AsyncClient) -> None:
    await _login(client, "usage-empty@example.com")
    body = (await client.get("/api/v1/usage")).json()
    assert body["daily"] == []
    assert body["totals"] == {
        "chat_requests": 0, "input_tokens": 0, "output_tokens": 0,
        "transcription_minutes": 0.0, "embedding_chunks": 0, "mcp_calls": 0,
    }


async def test_days_parameter_is_validated(client: httpx.AsyncClient) -> None:
    await _login(client, "usage-days@example.com")
    assert (await client.get("/api/v1/usage", params={"days": 0})).status_code == 422
    assert (await client.get("/api/v1/usage", params={"days": 91})).status_code == 422
    assert (await client.get("/api/v1/usage", params={"days": 7})).status_code == 200


async def test_chat_turn_counts_request_and_provider_tokens(client: httpx.AsyncClient) -> None:
    await _login(client, "usage-chat@example.com")
    conversation = (await client.post("/api/v1/conversations", json={})).json()["id"]
    for _ in range(2):
        response = await client.post(
            f"/api/v1/conversations/{conversation}/messages/stream", json={"content": "private question"}
        )
        assert response.status_code == 200
    totals = await _totals(client)
    assert totals["chat_requests"] == 2
    # The fake provider reports Usage(4, 2) per round.
    assert totals["input_tokens"] == 8 and totals["output_tokens"] == 4


async def test_usage_is_scoped_to_the_user(client: httpx.AsyncClient) -> None:
    await _login(client, "usage-a@example.com")
    conversation = (await client.post("/api/v1/conversations", json={})).json()["id"]
    await client.post(f"/api/v1/conversations/{conversation}/messages/stream", json={"content": "hi"})
    assert (await _totals(client))["chat_requests"] == 1

    client.cookies.clear()
    await _login(client, "usage-b@example.com")
    assert (await _totals(client))["chat_requests"] == 0


async def test_row_level_security_hides_other_users_counters(client: httpx.AsyncClient) -> None:
    first = await _login(client, "usage-rls-a@example.com")
    client.cookies.clear()
    second = await _login(client, "usage-rls-b@example.com")
    async with user_session(first) as session:
        await usage.add(session, first, {usage.MCP_CALLS: 3})
    async with user_session(second) as session:
        assert (await session.scalars(select(UsageRecord))).all() == []
        # A write for someone else's user_id violates the policy's WITH CHECK clause.
        with pytest.raises(DBAPIError):
            await usage.add(session, first, {usage.MCP_CALLS: 1})
    async with system_session() as session:
        assert (await session.scalars(select(UsageRecord))).all() == []


async def test_application_role_cannot_delete_counters(client: httpx.AsyncClient) -> None:
    user_id = await _login(client, "usage-delete@example.com")
    async with user_session(user_id) as session:
        await usage.add(session, user_id, {usage.MCP_CALLS: 1})
    with pytest.raises(DBAPIError):
        async with user_session(user_id) as session:
            await session.execute(text("DELETE FROM usage_records"))


async def test_add_accumulates_per_day_and_skips_zero(client: httpx.AsyncClient) -> None:
    user_id = await _login(client, "usage-add@example.com")
    yesterday = date.today() - timedelta(days=1)
    async with user_session(user_id) as session:
        await usage.add(session, user_id, {usage.MCP_CALLS: 2, usage.EMBEDDING_CHUNKS: 0})
        await usage.add(session, user_id, {usage.MCP_CALLS: 3})
        await usage.add(session, user_id, {usage.MCP_CALLS: 7}, day=yesterday)
        with pytest.raises(ValueError):
            await usage.add(session, user_id, {"unknown": 1})
    body = (await client.get("/api/v1/usage", params={"days": 2})).json()
    assert body["totals"]["mcp_calls"] == 12
    assert [item["mcp_calls"] for item in body["daily"]] == [5, 7]
    only_today = (await client.get("/api/v1/usage", params={"days": 1})).json()
    assert only_today["totals"]["mcp_calls"] == 5


async def test_indexing_counts_embedded_chunks(client: httpx.AsyncClient, memory_storage) -> None:
    user_id = await _login(client, "usage-index@example.com")
    response = await client.post(
        "/api/v1/files/upload", files={"file": ("notes.txt", b"alpha beta gamma", "text/plain")}
    )
    assert response.status_code == 201
    async with user_session(user_id) as session:
        document_id = await session.scalar(select(Document.id))
    assert document_id
    await process_index_document(user_id, document_id, memory_storage, FakeEmbeddingProvider())
    assert (await _totals(client))["embedding_chunks"] == 1


async def test_transcription_counts_audio_minutes(client: httpx.AsyncClient, memory_storage) -> None:
    user_id = await _login(client, "usage-audio@example.com")
    response = await client.post("/api/v1/audio/memos", files={"file": ("a.webm", WEBM, "audio/webm")})
    assert response.status_code == 201
    memo_id = response.json()["id"]

    async def ninety_seconds(data: bytes, extension: str) -> list[bytes]:
        return [b"\x00" * (SEGMENT_BITRATE // 8 * 60), b"\x00" * (SEGMENT_BITRATE // 8 * 30)]

    transcriber = FakeTranscriptionProvider(["one", "two"])
    await process_memo(user_id, memo_id, memory_storage, transcriber, FakeEmbeddingProvider(), ninety_seconds)
    totals = await _totals(client)
    assert totals["transcription_minutes"] == 1.5
    assert totals["embedding_chunks"] == 1


async def test_mcp_tool_calls_are_counted(client: httpx.AsyncClient) -> None:
    user_id = await _login(client, "usage-mcp@example.com")
    created = await client.post("/api/v1/tokens", json={"name": "t", "scopes": ["tasks:read"]})
    token = created.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_tasks", "arguments": {}}}
    listing = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    assert (await client.post("/mcp", json=call, headers=headers)).status_code == 200
    assert (await client.post("/mcp", json=call, headers=headers)).status_code == 200
    assert (await client.post("/mcp", json=listing, headers=headers)).status_code == 200
    # Only tools/call counts; the listing does not.
    assert (await _totals(client))["mcp_calls"] == 2
    async with user_session(user_id) as session:
        assert await session.get(User, user_id)
