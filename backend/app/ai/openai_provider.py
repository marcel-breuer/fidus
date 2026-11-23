from collections.abc import AsyncIterator
from typing import Any

from app.ai.config import get_model_config
from app.ai.providers import ChatEvent, ChatRequest, Completed, TextDelta, ToolCall, Usage


class OpenAIChatProvider:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        input_items: list[dict[str, str]] = []
        if request.system is not None:
            input_items.append({"role": "system", "content": request.system})
        input_items.extend({"role": item.role, "content": item.content} for item in request.messages)
        response = await self.client.responses.create(
            model=get_model_config().chat,
            input=input_items,
            stream=True,
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
