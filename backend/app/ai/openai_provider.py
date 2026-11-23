from collections.abc import AsyncIterator
from typing import Any

from app.ai.config import get_model_config
from app.ai.providers import (
    ChatEvent,
    ChatRequest,
    Completed,
    TextDelta,
    ToolCall,
    Usage,
    WebSearchResult,
    WebSource,
)


class OpenAIChatProvider:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        input_items: list[dict[str, Any]] = []
        if request.system is not None:
            input_items.append({"role": "system", "content": request.system})
        for item in request.messages:
            if item.tool_call is not None:
                input_items.append({
                    "type": "function_call", "call_id": item.tool_call.id,
                    "name": item.tool_call.name, "arguments": item.tool_call.arguments_json,
                })
            elif item.role == "tool":
                input_items.append({
                    "type": "function_call_output", "call_id": item.tool_call_id, "output": item.content,
                })
            else:
                input_items.append({"role": item.role, "content": item.content})
        options: dict[str, Any] = {}
        if request.tools:
            options["tools"] = [
                {"type": "function", "name": tool.name, "description": tool.description,
                 "parameters": tool.parameters}
                for tool in request.tools
            ]
        response = await self.client.responses.create(
            model=get_model_config().chat,
            input=input_items,
            stream=True,
            **options,
        )
        async for event in response:
            event_type = getattr(event, "type", None)
            if event_type == "response.output_text.delta":
                yield TextDelta(text=event.delta)
            elif event_type == "response.output_item.done":
                item = getattr(event, "item", None)
                if getattr(item, "type", None) == "function_call":
                    yield ToolCall(
                        id=getattr(item, "call_id", getattr(item, "id", "")),
                        name=item.name,
                        arguments_json=item.arguments,
                    )
            elif event_type == "response.completed":
                usage = event.response.usage
                yield Completed(
                    usage=Usage(
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                    )
                )


def create_openai_chat_provider(api_key: str) -> OpenAIChatProvider:
    from openai import AsyncOpenAI

    return OpenAIChatProvider(AsyncOpenAI(api_key=api_key))


class OpenAIEmbeddingProvider:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        config = get_model_config()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 64):
            response = await self.client.embeddings.create(
                model=config.embedding,
                input=texts[start:start + 64],
                dimensions=config.embedding_dimensions,
            )
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda item: item.index))
        return vectors


def create_openai_embedding_provider(api_key: str) -> OpenAIEmbeddingProvider:
    from openai import AsyncOpenAI

    return OpenAIEmbeddingProvider(AsyncOpenAI(api_key=api_key))


class OpenAIWebSearch:
    """Web search through the Responses API `web_search` tool, with an injected client."""

    def __init__(self, client: Any) -> None:
        self.client = client

    async def search(self, query: str) -> WebSearchResult:
        response = await self.client.responses.create(
            model=get_model_config().chat,
            input=query,
            tools=[{"type": "web_search"}],
        )
        answer_parts: list[str] = []
        sources: dict[str, WebSource] = {}
        for item in getattr(response, "output", None) or []:
            if getattr(item, "type", None) != "message":
                continue
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) != "output_text":
                    continue
                answer_parts.append(getattr(part, "text", "") or "")
                for annotation in getattr(part, "annotations", None) or []:
                    url = getattr(annotation, "url", None)
                    if getattr(annotation, "type", None) == "url_citation" and url and url not in sources:
                        sources[url] = WebSource(title=getattr(annotation, "title", None) or url, url=url)
        return WebSearchResult(answer="\n".join(answer_parts).strip(), sources=list(sources.values()))


def create_openai_web_search(api_key: str) -> OpenAIWebSearch:
    from openai import AsyncOpenAI

    return OpenAIWebSearch(AsyncOpenAI(api_key=api_key))
