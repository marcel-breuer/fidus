from types import SimpleNamespace as NS

from app.ai.openai_provider import OpenAIChatProvider, OpenAIWebSearch
from app.ai.providers import ChatMessage, ChatRequest, ToolCall, ToolSpec


class FakeResponses:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


async def test_openai_web_search_uses_hosted_tool_and_extracts_citations() -> None:
    annotation = NS(type="url_citation", url="https://a.test", title="A")
    duplicate = NS(type="url_citation", url="https://a.test", title="A again")
    other = NS(type="file_citation", url=None, title=None)
    response = NS(output=[
        NS(type="web_search_call"),
        NS(type="message", content=[
            NS(type="output_text", text="Answer.", annotations=[annotation, duplicate, other]),
            NS(type="refusal"),
        ]),
    ])
    responses = FakeResponses(response)
    result = await OpenAIWebSearch(NS(responses=responses)).search("news")
    assert responses.calls[0]["tools"] == [{"type": "web_search"}]
    assert responses.calls[0]["input"] == "news"
    assert result.answer == "Answer."
    assert [(item.title, item.url) for item in result.sources] == [("A", "https://a.test")]


async def test_openai_web_search_tolerates_empty_output() -> None:
    result = await OpenAIWebSearch(NS(responses=FakeResponses(NS(output=None)))).search("x")
    assert result.answer == "" and result.sources == []


async def test_chat_provider_sends_tools_and_tool_history() -> None:
    class Stream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class Responses:
        def __init__(self) -> None:
            self.kwargs: dict = {}

        async def create(self, **kwargs: object) -> Stream:
            self.kwargs = kwargs
            return Stream()

    responses = Responses()
    call = ToolCall("c1", "web_search", '{"query":"x"}')
    request = ChatRequest(
        system="s",
        messages=[
            ChatMessage("user", "hi"),
            ChatMessage("assistant", "", tool_call=call),
            ChatMessage("tool", "out", tool_call_id="c1"),
        ],
        tools=[ToolSpec("web_search", "d", {"type": "object"})],
    )
    async for _ in OpenAIChatProvider(NS(responses=responses)).stream(request):
        pass
    assert responses.kwargs["tools"] == [
        {"type": "function", "name": "web_search", "description": "d", "parameters": {"type": "object"}}
    ]
    assert responses.kwargs["input"][2:] == [
        {"type": "function_call", "call_id": "c1", "name": "web_search", "arguments": '{"query":"x"}'},
        {"type": "function_call_output", "call_id": "c1", "output": "out"},
    ]
