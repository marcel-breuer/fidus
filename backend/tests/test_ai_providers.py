from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.ai import deps
from app.ai.fakes import FakeChatProvider
from app.ai.openai_provider import OpenAIChatProvider
from app.ai.providers import ChatMessage, ChatRequest, Completed, TextDelta, ToolCall, Usage


async def _collect(provider, request) -> list[object]:
    return [event async for event in provider.stream(request)]


async def test_fake_chat_provider_records_requests_and_scripted_events() -> None:
    request = ChatRequest(system="Be concise", messages=[ChatMessage("user", "Hello")], tools=[])
    fake = FakeChatProvider([TextDelta("Hi"), Completed(Usage(2, 1))])
    assert await _collect(fake, request) == [TextDelta("Hi"), Completed(Usage(2, 1))]
    assert fake.requests == [request]


async def test_openai_provider_maps_text_tool_and_completion_events() -> None:
    events = [
        SimpleNamespace(type="response.output_text.delta", delta="Hello"),
        SimpleNamespace(type="response.output_item.done", item=SimpleNamespace(
            type="function_call", call_id="call-1", name="lookup", arguments='{"q":"x"}'
        )),
        SimpleNamespace(type="response.completed", response=SimpleNamespace(
            usage=SimpleNamespace(input_tokens=4, output_tokens=3)
        )),
    ]

    class Stream:
        def __aiter__(self) -> AsyncIterator[SimpleNamespace]:
            async def iterate():
                for event in events:
                    yield event
            return iterate()

    class Responses:
        calls: list[dict[str, object]] = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return Stream()

    class Client:
        def __init__(self) -> None:
            self.responses = Responses()

    client = Client()
    provider = OpenAIChatProvider(client)
    request = ChatRequest(system="system", messages=[ChatMessage("user", "Hi")], tools=[])
    result = await _collect(provider, request)
    assert result == [
        TextDelta("Hello"), ToolCall("call-1", "lookup", '{"q":"x"}'), Completed(Usage(4, 3))
    ]
    assert client.responses.calls[0]["stream"] is True
    assert client.responses.calls[0]["input"] == [
        {"role": "system", "content": "system"}, {"role": "user", "content": "Hi"}
    ]


def test_chat_provider_requires_configured_key(monkeypatch) -> None:
    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(openai_api_key=""))
    with pytest.raises(HTTPException) as error:
        deps.get_chat_provider()
    assert error.value.status_code == 503
    assert error.value.detail == "AI_NOT_CONFIGURED"
