import json

import httpx
import pytest
from sqlalchemy import select

from app.ai.fakes import FakeWebSearchProvider, SequencedChatProvider
from app.ai.providers import Completed, TextDelta, ToolCall, Usage
from app.db.models import AgentAction, AuditLog, Document, Memory, Task
from app.db.session import user_session
from app.services import chat
from app.worker.tasks import process_index_document
from tests.helpers import login, register


@pytest.fixture
def chat_provider() -> SequencedChatProvider:
    return SequencedChatProvider([])


def _call(name: str, arguments: dict | str, call_id: str = "call-1") -> ToolCall:
    return ToolCall(call_id, name, arguments if isinstance(arguments, str) else json.dumps(arguments))


def _round(*events: object) -> list[object]:
    return [*events, Completed(Usage(3, 2))]


async def _login(client: httpx.AsyncClient, email: str) -> str:
    await register(client, email)  # a repeated sign-in for the same user is fine
    assert (await login(client, email)).status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    return (await client.get("/api/v1/users/me")).json()["id"]


async def _conversation(client: httpx.AsyncClient) -> str:
    return (await client.post("/api/v1/conversations", json={})).json()["id"]


def _events(body: str) -> list[tuple[str, dict]]:
    result = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        name = next(line[7:] for line in lines if line.startswith("event: "))
        result.append((name, json.loads("\n".join(line[6:] for line in lines if line.startswith("data: ")))))
    return result


async def _ask(client: httpx.AsyncClient, conversation_id: str, text: str = "Question") -> list[tuple[str, dict]]:
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages/stream", json={"content": text}
    )
    assert response.status_code == 200
    return _events(response.text)


async def test_web_search_tool_feeds_result_back_and_stores_citations(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, web_search: FakeWebSearchProvider
) -> None:
    await _login(client, "web@example.com")
    conversation_id = await _conversation(client)
    chat_provider.rounds = [
        _round(_call("web_search", {"query": "weather"})),
        _round(TextDelta("It is sunny [1]."))
    ]
    events = await _ask(client, conversation_id)
    assert [name for name, _ in events] == ["message", "tool", "delta", "citations", "done"]
    assert events[1][1] == {"name": "web_search", "status": "done"}
    assert events[3][1]["items"] == [
        {"type": "web", "title": "Example", "url": "https://example.com/a", "ref": 1}
    ]
    assert web_search.queries == ["weather"]

    second = chat_provider.requests[1]
    assert second.messages[-2].tool_call and second.messages[-2].tool_call.name == "web_search"
    assert second.messages[-1].role == "tool" and second.messages[-1].tool_call_id == "call-1"
    assert second.messages[-1].content.startswith("<tool_result>")
    assert '"ref": 1' in second.messages[-1].content

    page = (await client.get(f"/api/v1/conversations/{conversation_id}/messages")).json()["items"]
    assistant = page[-1]
    assert assistant["content"] == "It is sunny [1]."
    assert assistant["citations"][0]["url"] == "https://example.com/a"
    assert assistant["tool_calls"] == [{"name": "web_search", "status": "done"}]
    assert (assistant["input_tokens"], assistant["output_tokens"]) == (6, 4)


async def test_web_results_with_unsafe_schemes_are_dropped(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, web_search: FakeWebSearchProvider
) -> None:
    from app.ai.providers import WebSearchResult, WebSource

    web_search.result = WebSearchResult("a", [WebSource("bad", "javascript:alert(1)"), WebSource("ok", "https://ok.test")])
    await _login(client, "scheme@example.com")
    chat_provider.rounds = [_round(_call("web_search", {"query": "q"})), _round(TextDelta("x"))]
    events = await _ask(client, await _conversation(client))
    assert [item["url"] for item in dict(events)["citations"]["items"]] == ["https://ok.test"]


async def test_knowledge_tool_cites_own_files_only(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, memory_storage
) -> None:
    from app.ai.fakes import FakeEmbeddingProvider

    owner_id = await _login(client, "rag-owner@example.com")
    upload = await client.post(
        "/api/v1/files/upload", files={"file": ("plan.txt", b"quarterly budget zebra", "text/plain")}
    )
    node_id = upload.json()["id"]
    async with user_session(owner_id) as session:
        document_id = await session.scalar(select(Document.id).where(Document.node_id == node_id))
    await process_index_document(owner_id, document_id, memory_storage, FakeEmbeddingProvider())

    chat_provider.rounds = [
        _round(_call("search_knowledge", {"query": "budget zebra"})), _round(TextDelta("See [1]."))
    ] * 2
    events = await _ask(client, await _conversation(client))
    citation = dict(events)["citations"]["items"][0]
    assert citation["type"] == "file" and citation["file_name"] == "plan.txt" and citation["node_id"] == node_id

    await _login(client, "rag-other@example.com")
    events = await _ask(client, await _conversation(client))
    assert "citations" not in dict(events)
    assert '"results": []' in chat_provider.requests[-1].messages[-1].content


async def test_conversation_search_tool_returns_references_to_earlier_messages(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider
) -> None:
    await _login(client, "history@example.com")
    first = await _conversation(client)
    chat_provider.rounds = [_round(TextDelta("Noted."))]
    await _ask(client, first, "My passport number ends with pineapple")
    chat_provider.requests.clear()
    second = await _conversation(client)
    chat_provider.rounds = [
        _round(_call("search_conversations", {"query": "pineapple"})), _round(TextDelta("Found [1] [2]."))
    ]
    events = await _ask(client, second, "What did I say about pineapple?")
    items = dict(events)["citations"]["items"]
    assert items[0]["type"] == "conversation" and items[0]["conversation_id"] in {first, second}
    assert "pineapple" in items[0]["snippet"] and "<b>" not in items[0]["snippet"]


async def test_write_tool_waits_for_confirmation_then_runs_once_with_audit(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider
) -> None:
    user_id = await _login(client, "ask@example.com")
    conversation_id = await _conversation(client)
    chat_provider.rounds = [_round(TextDelta("Sure. "), _call("remember", {"content": "Likes tea"}))]
    events = await _ask(client, conversation_id, "Remember I like tea")
    names = [name for name, _ in events]
    assert names == ["message", "delta", "tool", "action", "done"]
    assert len(chat_provider.requests) == 1
    action = dict(events)["action"]
    assert action["tool"] == "remember" and action["status"] == "pending"
    assert action["arguments"] == {"content": "Likes tea"}
    assert (await client.get("/api/v1/memories")).json() == []

    listed = (await client.get(f"/api/v1/conversations/{conversation_id}/actions")).json()
    assert [(item["id"], item["status"]) for item in listed] == [(action["id"], "pending")]
    assert listed[0]["message_id"] == dict(events)["done"]["message_id"]

    approved = await client.post(f"/api/v1/agent/actions/{action['id']}/approve")
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    memories = (await client.get("/api/v1/memories")).json()
    assert [(item["content"], item["source"]) for item in memories] == [("Likes tea", "agent")]
    audit = (await client.get("/api/v1/agent/audit")).json()
    assert [(item["action"], item["target_type"], item["target_id"]) for item in audit] == [
        ("agent.remember", "memory", memories[0]["id"])
    ]
    assert (await client.post(f"/api/v1/agent/actions/{action['id']}/approve")).status_code == 409
    assert (await client.post(f"/api/v1/agent/actions/{action['id']}/reject")).status_code == 409
    async with user_session(user_id) as session:
        assert len((await session.scalars(select(Memory))).all()) == 1


async def test_rejected_action_changes_nothing(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider
) -> None:
    user_id = await _login(client, "reject@example.com")
    chat_provider.rounds = [_round(_call("create_task", {"title": "Buy milk"}))]
    events = await _ask(client, await _conversation(client))
    action_id = dict(events)["action"]["id"]
    rejected = await client.post(f"/api/v1/agent/actions/{action_id}/reject")
    assert rejected.json()["status"] == "rejected"
    async with user_session(user_id) as session:
        assert (await session.scalars(select(Task))).all() == []
        assert (await session.scalars(select(AuditLog))).all() == []


async def test_decision_outcome_is_sent_to_model_and_assistant_continues(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider
) -> None:
    await _login(client, "continuation@example.com")
    conversation_id = await _conversation(client)
    chat_provider.rounds = [_round(_call("remember", {"content": "Likes tea"}))]
    events = await _ask(client, conversation_id)
    action_id = dict(events)["action"]["id"]
    assert (await client.post(f"/api/v1/agent/actions/{action_id}/reject")).status_code == 200
    chat_provider.rounds.append(_round(TextDelta("Understood; I will not save that.")))
    continued = await client.post(
        f"/api/v1/conversations/{conversation_id}/actions/{action_id}/continue"
    )
    assert continued.status_code == 200
    assert [event for event, _ in _events(continued.text)] == ["delta", "done"]
    request = chat_provider.requests[-1]
    assert request.messages[-1].role == "system"
    assert "rejected" in request.messages[-1].content
    assert "remember" in request.messages[-1].content


async def test_other_user_cannot_continue_action(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider
) -> None:
    await _login(client, "continue-owner@example.com")
    conversation_id = await _conversation(client)
    chat_provider.rounds = [_round(_call("remember", {"content": "private"}))]
    action_id = dict(await _ask(client, conversation_id))["action"]["id"]
    await client.post(f"/api/v1/agent/actions/{action_id}/reject")
    await _login(client, "continue-other@example.com")
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/actions/{action_id}/continue"
    )
    assert response.status_code == 404


async def test_allow_mode_executes_write_immediately_and_audits(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider
) -> None:
    user_id = await _login(client, "allow@example.com")
    assert (await client.put("/api/v1/agent/settings", json={"write_mode": "allow"})).status_code == 200
    chat_provider.rounds = [
        _round(_call("create_task", {"title": "Buy milk", "due_at": "2030-01-01T10:00:00+00:00"})),
        _round(TextDelta("Done.")),
    ]
    events = await _ask(client, await _conversation(client))
    assert [name for name, _ in events] == ["message", "tool", "delta", "done"]
    assert len(chat_provider.requests) == 2
    async with user_session(user_id) as session:
        task = (await session.scalars(select(Task))).one()
        entry = (await session.scalars(select(AuditLog))).one()
        assert (await session.scalars(select(AgentAction))).all() == []
    assert task.title == "Buy milk" and task.user_id == user_id
    assert (entry.action, entry.target_type, entry.target_id, entry.actor) == (
        "agent.create_task", "task", task.id, "agent"
    )
    assert "Buy milk" not in json.dumps(entry.details)


async def test_other_user_cannot_see_or_decide_actions(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider
) -> None:
    await _login(client, "action-a@example.com")
    conversation_id = await _conversation(client)
    chat_provider.rounds = [_round(_call("remember", {"content": "private"}))]
    action_id = dict(await _ask(client, conversation_id))["action"]["id"]
    await _login(client, "action-b@example.com")
    assert (await client.post(f"/api/v1/agent/actions/{action_id}/approve")).status_code == 404
    assert (await client.post(f"/api/v1/agent/actions/{action_id}/reject")).status_code == 404
    assert (await client.get(f"/api/v1/conversations/{conversation_id}/actions")).status_code == 404
    assert (await client.get("/api/v1/memories")).json() == []
    await _login(client, "action-a@example.com")
    assert (await client.get(f"/api/v1/conversations/{conversation_id}/actions")).json()[0]["status"] == "pending"


async def test_memories_are_injected_for_their_owner_only(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider
) -> None:
    await _login(client, "inject-a@example.com")
    await client.post("/api/v1/memories", json={"content": "Lives in Hamburg"})
    chat_provider.rounds = [_round(TextDelta("ok"))]
    await _ask(client, await _conversation(client))
    assert "Lives in Hamburg" in (chat_provider.requests[0].system or "")

    await _login(client, "inject-b@example.com")
    chat_provider.rounds = [_round(TextDelta("ok"))] * 2
    await _ask(client, await _conversation(client))
    assert "Hamburg" not in (chat_provider.requests[1].system or "")


async def test_unknown_tool_and_invalid_arguments_return_errors_to_the_model(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider
) -> None:
    await _login(client, "bad-tool@example.com")
    chat_provider.rounds = [
        _round(_call("run_sql", {"query": "drop table users"}, "c1"), _call("web_search", "{not json", "c2")),
        _round(TextDelta("Sorry.")),
    ]
    events = await _ask(client, await _conversation(client))
    assert [(n, d.get("status")) for n, d in events if n == "tool"] == [("tool", "error"), ("tool", "error")]
    outputs = [m.content for m in chat_provider.requests[1].messages if m.role == "tool"]
    assert 'UNKNOWN_TOOL' in outputs[0] and 'INVALID_ARGUMENTS' in outputs[1]
    assert events[-1][0] == "done"


async def test_tools_follow_module_enablement(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, owner_engine
) -> None:
    await _login(client, "modules@example.com")
    async with owner_engine.begin() as connection:
        await connection.exec_driver_sql(
            "INSERT INTO module_settings (module_key, enabled) VALUES ('files', false), ('tasks', false)"
        )
    try:
        chat_provider.rounds = [_round(TextDelta("ok"))]
        await _ask(client, await _conversation(client))
        names = {tool.name for tool in chat_provider.requests[0].tools}
        assert names == {"search_conversations", "web_search", "remember"}
    finally:
        async with owner_engine.begin() as connection:
            await connection.exec_driver_sql("DELETE FROM module_settings WHERE module_key IN ('files', 'tasks')")


async def test_approving_a_task_after_tasks_module_is_disabled_fails_safely(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, owner_engine
) -> None:
    user_id = await _login(client, "late-disable@example.com")
    chat_provider.rounds = [_round(_call("create_task", {"title": "Later"}))]
    action_id = dict(await _ask(client, await _conversation(client)))["action"]["id"]
    async with owner_engine.begin() as connection:
        await connection.exec_driver_sql("INSERT INTO module_settings (module_key, enabled) VALUES ('tasks', false)")
    try:
        result = await client.post(f"/api/v1/agent/actions/{action_id}/approve")
        assert result.json()["status"] == "failed"
    finally:
        async with owner_engine.begin() as connection:
            await connection.exec_driver_sql("DELETE FROM module_settings WHERE module_key = 'tasks'")
    async with user_session(user_id) as session:
        assert (await session.scalars(select(Task))).all() == []


async def test_tool_loop_is_bounded_and_last_round_offers_no_tools(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider
) -> None:
    await _login(client, "bounded@example.com")
    looping = _round(_call("web_search", {"query": "again"}))
    chat_provider.rounds = [looping] * chat.MAX_TOOL_ROUNDS + [_round(TextDelta("Final."))]
    events = await _ask(client, await _conversation(client))
    assert len(chat_provider.requests) == chat.MAX_TOOL_ROUNDS + 1
    assert chat_provider.requests[-1].tools == []
    assert chat_provider.requests[0].tools
    assert events[-1][0] == "done"


async def test_provider_failure_inside_tool_loop_reports_generic_error(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, web_search: FakeWebSearchProvider
) -> None:
    async def boom(query: str):
        raise RuntimeError("private upstream detail")

    web_search.search = boom  # type: ignore[method-assign]
    await _login(client, "boom@example.com")
    chat_provider.rounds = [_round(_call("web_search", {"query": "x"})), _round(TextDelta("recovered"))]
    response = await client.post(
        f"/api/v1/conversations/{await _conversation(client)}/messages/stream", json={"content": "q"}
    )
    assert "private upstream detail" not in response.text
    outputs = [m.content for m in chat_provider.requests[1].messages if m.role == "tool"]
    assert "TOOL_FAILED" in outputs[0]


async def _file_names(client: httpx.AsyncClient, folder_id: str | None = None) -> list[str]:
    params = {"parent_id": folder_id} if folder_id else {}
    return [item["name"] for item in (await client.get("/api/v1/files/nodes", params=params)).json()]


async def _propose(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, tool: str, arguments: dict
) -> dict:
    chat_provider.rounds = [_round(_call(tool, arguments))]
    return dict(await _ask(client, await _conversation(client)))["action"]


async def test_create_file_waits_for_confirmation_then_stores_version_audit_and_index_job(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _login(client, "filewriter@example.com")
    queued: list[str] = []

    async def record(user: str, document_id: str) -> None:
        queued.append(document_id)

    monkeypatch.setattr("app.services.indexing.enqueue_index_document", record)
    folder = (await client.post("/api/v1/files/folders", json={"name": "Notes", "parent_id": None})).json()
    action = await _propose(
        client, chat_provider, "create_file",
        {"name": "ideas.md", "content": "# Ideas\nzebra", "folder_id": folder["id"]},
    )
    assert action["status"] == "pending"
    assert await _file_names(client, folder["id"]) == []
    assert queued == []

    approved = await client.post(f"/api/v1/agent/actions/{action['id']}/approve")
    assert approved.json()["status"] == "approved"
    nodes = (await client.get("/api/v1/files/nodes", params={"parent_id": folder["id"]})).json()
    assert [(n["name"], n["kind"]) for n in nodes] == [("ideas.md", "file")]
    download = await client.get(f"/api/v1/files/nodes/{nodes[0]['id']}/download")
    assert download.content == b"# Ideas\nzebra"
    async with user_session(user_id) as session:
        document = (await session.scalars(select(Document))).one()
        entry = (await session.scalars(select(AuditLog))).one()
    assert document.node_id == nodes[0]["id"] and document.status == "pending"
    assert queued == [document.id]
    assert (entry.action, entry.target_type, entry.target_id, entry.actor) == (
        "agent.create_file", "file", nodes[0]["id"], "agent"
    )
    assert "zebra" not in json.dumps(entry.details)
    assert (await client.post(f"/api/v1/agent/actions/{action['id']}/approve")).status_code == 409


async def test_rejected_file_write_changes_nothing(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, memory_storage
) -> None:
    user_id = await _login(client, "filereject@example.com")
    action = await _propose(client, chat_provider, "create_file", {"name": "a.txt", "content": "x"})
    assert (await client.post(f"/api/v1/agent/actions/{action['id']}/reject")).json()["status"] == "rejected"
    assert await _file_names(client) == []
    assert memory_storage.objects == {}
    async with user_session(user_id) as session:
        assert (await session.scalars(select(AuditLog))).all() == []


async def test_allow_mode_update_file_adds_version_and_queues_indexing(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = await _login(client, "fileupdate@example.com")
    assert (await client.put("/api/v1/agent/settings", json={"write_mode": "allow"})).status_code == 200
    queued: list[str] = []

    async def record(user: str, document_id: str) -> None:
        queued.append(document_id)

    monkeypatch.setattr("app.services.indexing.enqueue_index_document", record)
    node = (await client.post(
        "/api/v1/files/upload", files={"file": ("todo.txt", b"old", "text/plain")}
    )).json()
    chat_provider.rounds = [
        _round(_call("update_file", {"node_id": node["id"], "content": "new text"})),
        _round(TextDelta("Saved.")),
    ]
    events = await _ask(client, await _conversation(client))
    assert [(n, d.get("status")) for n, d in events if n == "tool"] == [("tool", "done")]
    tool_output = chat_provider.requests[1].messages[-1].content
    assert '"version": 2' in tool_output and node["id"] in tool_output
    versions = (await client.get(f"/api/v1/files/nodes/{node['id']}/versions")).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert (await client.get(f"/api/v1/files/nodes/{node['id']}/download")).content == b"new text"
    assert (await client.get(f"/api/v1/files/nodes/{node['id']}/download?version=1")).content == b"old"
    assert len(queued) == 2  # the upload and the agent's new version
    async with user_session(user_id) as session:
        entry = (await session.scalars(select(AuditLog))).one()
    assert (entry.action, entry.target_type, entry.target_id) == ("agent.update_file", "file", node["id"])


async def test_file_tools_never_reach_another_users_files_or_folders(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider
) -> None:
    await _login(client, "file-a@example.com")
    folder = (await client.post("/api/v1/files/folders", json={"name": "Private", "parent_id": None})).json()
    node = (await client.post(
        "/api/v1/files/upload", files={"file": ("secret.txt", b"mine", "text/plain")}
    )).json()

    user_b = await _login(client, "file-b@example.com")
    assert (await client.put("/api/v1/agent/settings", json={"write_mode": "allow"})).status_code == 200
    chat_provider.rounds = [
        _round(
            _call("update_file", {"node_id": node["id"], "content": "overwritten"}, "c1"),
            _call("create_file", {"name": "x.txt", "content": "x", "folder_id": folder["id"]}, "c2"),
        ),
        _round(TextDelta("done")),
    ]
    events = await _ask(client, await _conversation(client))
    assert [d["status"] for n, d in events if n == "tool"] == ["error", "error"]
    tool_messages = [m.content for m in chat_provider.requests[-1].messages if m.role == "tool"]
    assert "NODE_NOT_FOUND" in tool_messages[0] and "PARENT_NOT_FOUND" in tool_messages[1]
    assert await _file_names(client) == []

    await _login(client, "file-a@example.com")
    versions = (await client.get(f"/api/v1/files/nodes/{node['id']}/versions")).json()
    assert [v["version"] for v in versions] == [1]
    assert await _file_names(client, folder["id"]) == []
    async with user_session(user_b) as session:
        assert (await session.scalars(select(AuditLog))).all() == []


async def test_other_user_cannot_approve_a_pending_file_write(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider
) -> None:
    await _login(client, "file-owner@example.com")
    action = await _propose(client, chat_provider, "create_file", {"name": "a.md", "content": "x"})
    await _login(client, "file-intruder@example.com")
    assert (await client.post(f"/api/v1/agent/actions/{action['id']}/approve")).status_code == 404
    await _login(client, "file-owner@example.com")
    assert await _file_names(client) == []


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"name": "report.pdf", "content": "x"}, "UNSUPPORTED_TYPE"),
        ({"name": "noextension", "content": "x"}, "UNSUPPORTED_TYPE"),
        ({"name": "../escape.md", "content": "x"}, "INVALID_NAME"),
        ({"name": "sub/dir.md", "content": "x"}, "INVALID_NAME"),
        ({"name": "..\\escape.md", "content": "x"}, "INVALID_NAME"),
        ({"name": "taken.md", "content": "x"}, "NAME_CONFLICT"),
        ({"name": "nul.txt", "content": "a\x00b"}, "UNSUPPORTED_TYPE"),
    ],
)
async def test_create_file_rejects_unsafe_or_conflicting_input(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, memory_storage, arguments: dict, code: str
) -> None:
    await _login(client, "filevalid@example.com")
    assert (await client.put("/api/v1/agent/settings", json={"write_mode": "allow"})).status_code == 200
    await client.post("/api/v1/files/upload", files={"file": ("taken.md", b"keep", "text/markdown")})
    stored = dict(memory_storage.objects)
    chat_provider.rounds = [_round(_call("create_file", arguments)), _round(TextDelta("no"))]
    events = await _ask(client, await _conversation(client))
    assert [d["status"] for n, d in events if n == "tool"] == ["error"]
    assert code in chat_provider.requests[1].messages[-1].content
    assert memory_storage.objects == stored
    assert await _file_names(client) == ["taken.md"]


async def test_file_tools_enforce_size_limit_and_text_only_updates(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _login(client, "filelimits@example.com")
    assert (await client.put("/api/v1/agent/settings", json={"write_mode": "allow"})).status_code == 200
    monkeypatch.setattr("app.services.files.MAX_UPLOAD_BYTES", 10)
    pdf = (await client.post(
        "/api/v1/files/upload", files={"file": ("doc.pdf", b"%PDF-1.4 x", "application/pdf")}
    )).json()
    chat_provider.rounds = [
        _round(
            _call("create_file", {"name": "big.txt", "content": "x" * 11}, "c1"),
            _call("update_file", {"node_id": pdf["id"], "content": "text"}, "c2"),
        ),
        _round(TextDelta("no")),
    ]
    await _ask(client, await _conversation(client))
    outputs = [m.content for m in chat_provider.requests[-1].messages if m.role == "tool"]
    assert "FILE_TOO_LARGE" in outputs[0] and "UNSUPPORTED_TYPE" in outputs[1]
    assert await _file_names(client) == ["doc.pdf"]
    versions = (await client.get(f"/api/v1/files/nodes/{pdf['id']}/versions")).json()
    assert [v["version"] for v in versions] == [1]


async def test_file_tools_follow_files_module_enablement(
    client: httpx.AsyncClient, chat_provider: SequencedChatProvider, owner_engine
) -> None:
    await _login(client, "filemodule@example.com")
    chat_provider.rounds = [_round(TextDelta("ok"))]
    await _ask(client, await _conversation(client))
    assert {"create_file", "update_file"} <= {tool.name for tool in chat_provider.requests[0].tools}
    chat_provider.requests.clear()

    action = await _propose(client, chat_provider, "create_file", {"name": "late.md", "content": "x"})
    async with owner_engine.begin() as connection:
        await connection.exec_driver_sql("INSERT INTO module_settings (module_key, enabled) VALUES ('files', false)")
    try:
        chat_provider.requests.clear()
        chat_provider.rounds = [_round(TextDelta("ok"))]
        await _ask(client, await _conversation(client))
        assert not {"create_file", "update_file"} & {tool.name for tool in chat_provider.requests[-1].tools}
        assert (await client.post(f"/api/v1/agent/actions/{action['id']}/approve")).json()["status"] == "failed"
    finally:
        async with owner_engine.begin() as connection:
            await connection.exec_driver_sql("DELETE FROM module_settings WHERE module_key = 'files'")
    assert await _file_names(client) == []
