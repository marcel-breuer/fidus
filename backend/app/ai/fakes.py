from collections.abc import AsyncIterator, Iterable

from app.ai.providers import ChatEvent, ChatRequest


class FakeChatProvider:
    def __init__(self, replies: Iterable[ChatEvent] = ()) -> None:
        self.replies = tuple(replies)
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        self.requests.append(request)
        for reply in self.replies:
            yield reply
