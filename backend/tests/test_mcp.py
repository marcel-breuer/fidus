from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.ai.fakes import KeywordEmbeddingProvider
from app.config import get_settings
from app.db.models import Document, Task, User
from app.db.session import system_session, user_session
from app.main import create_app
from app.mcp.protocol import SUPPORTED_PROTOCOL_VERSIONS
from app.mcp.tools import TOOLS
from app.modules.registry import ALL_SCOPES
from app.services import api_tokens
from app.worker.tasks import process_index_document
from tests.helpers import PASSWORD, register

ALL_TOOL_SCOPES = sorted(ALL_SCOPES)


async def _login(client: httpx.AsyncClient, email: str) -> str:
    registered = await register(client, email)
    assert registered.status_code == 201
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    return registered.json()["id"]


async def _signup(
    client: httpx.AsyncClient, email: str, scopes: list[str] | None = None
) -> tuple[str, str]:
    """Register a user, mint a token through the cookie session and return (user_id, token).
    Cookies are dropped afterwards so later calls authenticate with the bearer token alone."""
    user_id = await _login(client, email)
    created = await client.post("/api/v1/tokens", json={"name": "mcp", "scopes": scopes or ALL_TOOL_SCOPES})
    assert created.status_code == 201
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    return user_id, created.json()["token"]


async def rpc(
    client: httpx.AsyncClient, token: str | None, method: str, params: dict[str, Any] | None = None, id: int = 1
) -> httpx.Response:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        message["params"] = params
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return await client.post("/mcp", json=message, headers=headers)


async def call(
    client: httpx.AsyncClient, token: str, name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = await rpc(client, token, "tools/call", {"name": name, "arguments": arguments or {}})
    assert response.status_code == 200
    return response.json()


async def _index_file(client: httpx.AsyncClient, user_id: str, memory_storage, name: str, content: bytes) -> None:
    uploaded = await client.post("/api/v1/files/upload", files={"file": (name, content, "text/plain")})
    assert uploaded.status_code == 201
    async with user_session(user_id) as session:
        document_id = await session.scalar(select(Document.id).where(Document.node_id == uploaded.json()["id"]))
    assert document_id is not None
    await process_index_document(user_id, document_id, memory_storage, KeywordEmbeddingProvider())


# --- authentication -------------------------------------------------------------------------


async def test_missing_malformed_unknown_and_cookie_only_credentials_are_rejected(client: httpx.AsyncClient) -> None:
    missing = await rpc(client, None, "ping")
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"].startswith("Bearer")
    assert missing.json()["detail"] == "INVALID_TOKEN"
    assert (await rpc(client, "fidus_pat_" + "x" * 43, "ping")).status_code == 401
    assert (await rpc(client, "plain-text", "ping")).status_code == 401
    basic = await client.post("/mcp", json={}, headers={"Authorization": "Basic Zm9vOmJhcg=="})
    assert basic.status_code == 401

    # A valid session cookie is not accepted on the MCP endpoint.
    await _login(client, "mcp-cookie@example.com")
    cookie_only = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert cookie_only.status_code == 401


async def test_expired_and_revoked_tokens_are_rejected(client: httpx.AsyncClient) -> None:
    user_id = await _login(client, "mcp-expiry@example.com")
    async with user_session(user_id) as session:
        user = await session.get(User, user_id)
        assert user is not None
        _, expired = await api_tokens.create_token(
            session, user, "old", ["tasks:read"], 1, now=datetime.now(UTC) - timedelta(days=3)
        )
    created = (await client.post("/api/v1/tokens", json={"name": "x", "scopes": ["tasks:read"]})).json()
    client.cookies.clear()
    assert (await rpc(client, expired, "ping")).status_code == 401
    assert (await rpc(client, created["token"], "ping")).status_code == 200

    await _login_again(client, "mcp-expiry@example.com")
    assert (await client.delete(f"/api/v1/tokens/{created['id']}")).status_code == 204
    client.cookies.clear()
    assert (await rpc(client, created["token"], "ping")).status_code == 401


async def _login_again(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""


async def test_bearer_requests_need_no_csrf_token_even_with_a_session_cookie(client: httpx.AsyncClient) -> None:
    _, token = await _signup(client, "mcp-csrf@example.com")
    await _login_again(client, "mcp-csrf@example.com")
    client.headers.pop("X-CSRF-Token")
    assert client.cookies.get("fidus_session")
    assert (await rpc(client, token, "ping")).status_code == 200
    # The same cookie without the CSRF header is still refused on the REST API.
    assert (await client.post("/api/v1/tasks", json={"title": "x"})).status_code == 403


async def test_bearer_token_does_not_authenticate_rest_routes(client: httpx.AsyncClient) -> None:
    _, token = await _signup(client, "mcp-rest@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/tasks", headers=headers)).status_code == 401
    assert (await client.get("/api/v1/tokens", headers=headers)).status_code == 401
    payload = {"name": "x", "scopes": ["tasks:read"]}
    assert (await client.post("/api/v1/tokens", headers=headers, json=payload)).status_code == 401


async def test_failed_attempts_and_token_requests_are_rate_limited(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_rate_limit_attempts", 2)
    monkeypatch.setattr(settings, "mcp_rate_limit_requests", 3)
    _, token = await _signup(client, "mcp-limit@example.com")
    for _ in range(3):
        assert (await rpc(client, token, "ping")).status_code == 200
    limited = await rpc(client, token, "ping")
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1

    codes = [(await rpc(client, "fidus_pat_" + "y" * 43, "ping")).status_code for _ in range(3)]
    assert codes == [401, 401, 429]


# --- protocol -------------------------------------------------------------------------------


async def test_initialize_negotiates_version_and_declares_tools_only(client: httpx.AsyncClient) -> None:
    _, token = await _signup(client, "mcp-init@example.com")
    for requested in SUPPORTED_PROTOCOL_VERSIONS:
        result = (await rpc(client, token, "initialize", {"protocolVersion": requested, "capabilities": {}})).json()
        assert result["jsonrpc"] == "2.0" and result["id"] == 1
        assert result["result"]["protocolVersion"] == requested
    result = (await rpc(client, token, "initialize", {"protocolVersion": "1999-01-01"})).json()["result"]
    assert result["protocolVersion"] == SUPPORTED_PROTOCOL_VERSIONS[0]
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == "fidus"


async def test_notifications_and_client_responses_get_202_and_ping_works(client: httpx.AsyncClient) -> None:
    _, token = await _signup(client, "mcp-notify@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    notified = await client.post("/mcp", json=notification, headers=headers)
    assert notified.status_code == 202 and notified.content == b""
    answered = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 9, "result": {}}, headers=headers)
    assert answered.status_code == 202
    assert (await rpc(client, token, "ping", id=7)).json() == {"jsonrpc": "2.0", "id": 7, "result": {}}
    # The trailing-slash form is served as well.
    slash = await client.post("/mcp/", json={"jsonrpc": "2.0", "id": 2, "method": "ping"}, headers=headers)
    assert slash.status_code == 200


async def test_malformed_requests_and_unsupported_methods(client: httpx.AsyncClient) -> None:
    _, token = await _signup(client, "mcp-bad@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    parse = await client.post("/mcp", content=b"{not json", headers=headers)
    assert parse.status_code == 400 and parse.json()["error"]["code"] == -32700
    batch = await client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}], headers=headers)
    assert batch.status_code == 400 and batch.json()["error"]["code"] == -32600
    invalid = await client.post("/mcp", json={"id": 1, "method": "ping"}, headers=headers)
    assert invalid.json()["error"]["code"] == -32600
    unknown = await rpc(client, token, "resources/list")
    assert unknown.json()["error"]["code"] == -32601
    bad_version = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={**headers, "MCP-Protocol-Version": "1999-01-01"},
    )
    assert bad_version.status_code == 400
    assert (await client.get("/mcp", headers=headers)).status_code == 405
    assert (await client.delete("/mcp", headers=headers)).status_code == 405
    too_large = await client.post("/mcp", content=b" " * (1024 * 1024 + 1), headers=headers)
    assert too_large.status_code == 413


async def test_cross_origin_browser_requests_are_refused(client: httpx.AsyncClient) -> None:
    _, token = await _signup(client, "mcp-origin@example.com")
    response = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": f"Bearer {token}", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


# --- tools: listing, scopes and modules ----------------------------------------------------


async def test_tools_list_is_filtered_by_token_scopes(client: httpx.AsyncClient) -> None:
    _, full = await _signup(client, "mcp-list-a@example.com")
    names = [tool["name"] for tool in (await rpc(client, full, "tools/list")).json()["result"]["tools"]]
    assert names == [tool.name for tool in TOOLS]

    _, narrow = await _signup(client, "mcp-list-b@example.com", ["tasks:read", "files:read"])
    tools = (await rpc(client, narrow, "tools/list")).json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["list_tasks", "search_knowledge"]
    assert all(tool["inputSchema"]["type"] == "object" for tool in tools)
    assert tools[0]["annotations"]["readOnlyHint"] is True


async def test_scope_denial_blocks_the_call_without_side_effects(client: httpx.AsyncClient) -> None:
    user_id, token = await _signup(client, "mcp-scope@example.com", ["tasks:read"])
    denied = await call(client, token, "create_task", {"title": "Should not exist"})
    assert denied["error"]["code"] == -32001 and denied["error"]["data"] == {"required_scope": "tasks:write"}
    assert (await call(client, token, "search_conversations", {"query": "x"}))["error"]["code"] == -32001
    async with user_session(user_id) as session:
        assert (await session.scalars(select(Task))).all() == []
    assert (await call(client, token, "list_tasks"))["result"]["isError"] is False


async def test_disabled_module_hides_and_blocks_its_tools(client: httpx.AsyncClient) -> None:
    await _login(client, "mcp-module@example.com")  # first user is the admin
    token = (await client.post("/api/v1/tokens", json={"name": "m", "scopes": ALL_TOOL_SCOPES})).json()["token"]
    assert (await client.put("/api/v1/admin/modules/tasks", json={"enabled": False})).status_code == 200
    client.cookies.clear()
    names = [tool["name"] for tool in (await rpc(client, token, "tools/list")).json()["result"]["tools"]]
    assert "list_tasks" not in names and "create_task" not in names and "search_knowledge" in names
    blocked = await call(client, token, "list_tasks")
    assert blocked["error"]["code"] == -32002 and blocked["error"]["data"] == {"module": "tasks"}
    await _login_again(client, "mcp-module@example.com")
    assert (await client.put("/api/v1/admin/modules/tasks", json={"enabled": True})).status_code == 200
    client.cookies.clear()
    assert (await call(client, token, "list_tasks"))["result"]["isError"] is False


async def test_invalid_arguments_and_unknown_tools(client: httpx.AsyncClient) -> None:
    _, token = await _signup(client, "mcp-args@example.com")
    unknown = await call(client, token, "delete_everything")
    assert unknown["error"]["code"] == -32602 and unknown["error"]["message"] == "UNKNOWN_TOOL"
    for name, args in [
        ("create_task", {}),
        ("create_task", {"title": "   "}),
        ("create_task", {"title": "ok", "surprise": 1}),
        ("list_tasks", {"limit": 0}),
        ("search_knowledge", {"query": ""}),
        ("complete_task", {"task_id": 5}),
    ]:
        error = (await call(client, token, name, args))["error"]
        assert error["code"] == -32602 and error["message"] == "INVALID_ARGUMENTS", (name, args)
        assert all("input" not in entry for entry in error["data"])
    bad_cursor = (await call(client, token, "list_tasks", {"cursor": "garbage"}))["result"]
    assert bad_cursor["isError"] is True and bad_cursor["content"][0]["text"] == "INVALID_CURSOR"


# --- tools: behavior shared with REST -----------------------------------------------------


async def test_task_tools_match_the_rest_operations(client: httpx.AsyncClient) -> None:
    user_id, token = await _signup(client, "mcp-tasks@example.com")
    created = (await call(client, token, "create_task", {"title": "Buy milk", "notes": "2 liters"}))["result"]
    assert created["isError"] is False
    task = created["structuredContent"]
    assert task["title"] == "Buy milk" and task["notes"] == "2 liters" and task["done_at"] is None

    listed = (await call(client, token, "list_tasks"))["result"]["structuredContent"]
    assert [item["id"] for item in listed["items"]] == [task["id"]]

    done = (await call(client, token, "complete_task", {"task_id": task["id"]}))["result"]["structuredContent"]
    assert done["done_at"] is not None
    assert (await call(client, token, "list_tasks"))["result"]["structuredContent"]["items"] == []
    all_tasks = (await call(client, token, "list_tasks", {"status": "all"}))["result"]["structuredContent"]["items"]
    assert [item["id"] for item in all_tasks] == [task["id"]]

    # The REST adapter sees exactly what the MCP adapter wrote.
    await _login_again(client, "mcp-tasks@example.com")
    rest = (await client.get("/api/v1/tasks", params={"status": "all"})).json()
    assert rest["items"] == all_tasks
    async with user_session(user_id) as session:
        assert len((await session.scalars(select(Task))).all()) == 1


async def test_tool_text_content_mirrors_structured_content(client: httpx.AsyncClient) -> None:
    import json

    _, token = await _signup(client, "mcp-content@example.com")
    result = (await call(client, token, "create_task", {"title": "Mirror"}))["result"]
    assert result["content"][0]["type"] == "text"
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


async def test_conversation_tools_match_rest(client: httpx.AsyncClient) -> None:
    from app.services import conversations

    user_id, token = await _signup(client, "mcp-conv@example.com")
    async with user_session(user_id) as session:
        user = await session.get(User, user_id)
        assert user is not None
        conversation = await conversations.create_conversation(session, user, "Trip planning")
        await conversations.add_message(session, user, conversation.id, "user", "Remember the sunflower tickets")

    listed = (await call(client, token, "list_conversations"))["result"]["structuredContent"]
    assert [item["title"] for item in listed["items"]] == ["Trip planning"]
    found = (await call(client, token, "search_conversations", {"query": "sunflower"}))["result"]["structuredContent"]
    assert [item["conversation_id"] for item in found["results"]] == [conversation.id]
    assert "sunflower" in found["results"][0]["snippet"]

    await _login_again(client, "mcp-conv@example.com")
    rest = (await client.get("/api/v1/search/messages", params={"q": "sunflower"})).json()
    assert rest == found["results"]
    assert (await client.get("/api/v1/conversations")).json()["items"] == listed["items"]


async def test_knowledge_search_tool_returns_citations(client: httpx.AsyncClient, memory_storage) -> None:
    user_id = await _login(client, "mcp-knowledge@example.com")
    token = (await client.post("/api/v1/tokens", json={"name": "k", "scopes": ["files:read"]})).json()["token"]
    await _index_file(client, user_id, memory_storage, "plan.txt", b"quarterly budget emerald forecast")
    client.cookies.clear()

    result = (await call(client, token, "search_knowledge", {"query": "emerald forecast", "limit": 3}))["result"]
    assert result["isError"] is False
    hits = result["structuredContent"]["results"]
    assert hits and hits[0]["file_name"] == "plan.txt" and "emerald" in hits[0]["snippet"]

    await _login_again(client, "mcp-knowledge@example.com")
    rest = (await client.get("/api/v1/knowledge/search", params={"q": "emerald forecast", "limit": 3})).json()
    assert rest["results"] == hits


async def test_knowledge_search_reports_missing_ai_configuration_as_tool_error(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.deps import get_embedding_provider

    _, token = await _signup(client, "mcp-noai@example.com")
    transport = client._transport  # noqa: SLF001
    app = transport.app  # type: ignore[attr-defined]
    app.dependency_overrides.pop(get_embedding_provider)
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    # Protocol-level calls keep working without a provider key.
    assert (await rpc(client, token, "tools/list")).status_code == 200
    result = (await call(client, token, "search_knowledge", {"query": "anything"}))["result"]
    assert result["isError"] is True and result["content"][0]["text"] == "AI_NOT_CONFIGURED"


# --- cross-user isolation ------------------------------------------------------------------


async def test_tokens_never_reach_another_users_data(client: httpx.AsyncClient, memory_storage) -> None:
    from app.services import conversations

    owner_id = await _login(client, "mcp-owner@example.com")
    owner_token = (await client.post("/api/v1/tokens", json={"name": "o", "scopes": ALL_TOOL_SCOPES})).json()["token"]
    task_id = (await client.post("/api/v1/tasks", json={"title": "Owner secret"})).json()["id"]
    await _index_file(client, owner_id, memory_storage, "secret.txt", b"confidential tangerine merger")
    async with user_session(owner_id) as session:
        owner = await session.get(User, owner_id)
        assert owner is not None
        conversation = await conversations.create_conversation(session, owner, "Private chat")
        await conversations.add_message(session, owner, conversation.id, "user", "tangerine diary entry")
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)

    _, other_token = await _signup(client, "mcp-intruder@example.com")

    others_tasks = await call(client, other_token, "list_tasks", {"status": "all"})
    assert others_tasks["result"]["structuredContent"]["items"] == []
    stolen = (await call(client, other_token, "complete_task", {"task_id": task_id}))["result"]
    assert stolen["isError"] is True and stolen["content"][0]["text"] == "TASK_NOT_FOUND"
    assert (await call(client, other_token, "search_knowledge", {"query": "tangerine merger"}))["result"][
        "structuredContent"
    ]["results"] == []
    assert (await call(client, other_token, "search_conversations", {"query": "tangerine"}))["result"][
        "structuredContent"
    ]["results"] == []
    assert (await call(client, other_token, "list_conversations"))["result"]["structuredContent"]["items"] == []

    # The owner's task is untouched and still visible to the owner's token.
    owner_tasks = (await call(client, owner_token, "list_tasks"))["result"]["structuredContent"]["items"]
    assert [(item["id"], item["done_at"]) for item in owner_tasks] == [(task_id, None)]
    assert (await call(client, owner_token, "search_knowledge", {"query": "tangerine merger"}))["result"][
        "structuredContent"
    ]["results"]


async def test_token_identity_comes_from_the_token_not_the_request(client: httpx.AsyncClient) -> None:
    owner_id, _ = await _signup(client, "mcp-ident-a@example.com")
    other_id, other_token = await _signup(client, "mcp-ident-b@example.com")
    await call(client, other_token, "create_task", {"title": "Created by B"})
    async with system_session() as session:
        assert (await session.scalars(select(Task.user_id))).all() == []  # row-secured without context
    async with user_session(owner_id) as session:
        assert (await session.scalars(select(Task))).all() == []
    async with user_session(other_id) as session:
        assert [task.title for task in (await session.scalars(select(Task))).all()] == ["Created by B"]


# --- contract: MCP tools vs REST operations ------------------------------------------------


def test_every_tool_has_a_rest_operation_a_known_scope_and_module() -> None:
    from app.modules.registry import REGISTRY

    paths = create_app().openapi()["paths"]
    modules = {module.key: set(module.scopes) for module in REGISTRY}
    assert len({tool.name for tool in TOOLS}) == len(TOOLS)
    for tool in TOOLS:
        method, path = tool.rest_operation
        assert method in paths[path], tool.name
        assert tool.scope in ALL_SCOPES, tool.name
        assert tool.scope in modules[tool.module], tool.name
        assert (method == "get") == tool.read_only, tool.name
        assert tool.descriptor()["inputSchema"]["type"] == "object"


def test_mcp_endpoint_is_not_part_of_the_rest_schema() -> None:
    assert not [path for path in create_app().openapi()["paths"] if path.startswith("/mcp")]


# --- audit ---------------------------------------------------------------------------------


async def test_mcp_writes_are_audited_and_reads_and_denials_are_not(client: httpx.AsyncClient) -> None:
    await _login(client, "mcp-audit@example.com")
    scopes = ["tasks:read", "tasks:write"]
    created = (await client.post("/api/v1/tokens", json={"name": "a", "scopes": scopes})).json()
    narrow = (await client.post("/api/v1/tokens", json={"name": "r", "scopes": ["tasks:read"]})).json()["token"]
    client.cookies.clear()
    token = created["token"]
    task = (await call(client, token, "create_task", {"title": "Audited"}))["result"]["structuredContent"]
    await call(client, token, "complete_task", {"task_id": task["id"]})
    await call(client, token, "list_tasks")
    await call(client, token, "complete_task", {"task_id": "missing"})
    await call(client, narrow, "create_task", {"title": "Denied"})

    await _login_again(client, "mcp-audit@example.com")
    entries = (await client.get("/api/v1/agent/audit")).json()
    mcp = [e for e in entries if e["actor"] == "mcp"]
    assert sorted((e["action"], e["target_type"], e["target_id"]) for e in mcp) == [
        ("mcp.complete_task", "task", task["id"]),
        ("mcp.create_task", "task", task["id"]),
    ]
    assert token not in str(entries)
