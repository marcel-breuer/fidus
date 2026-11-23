import hashlib
import math
import re
from collections.abc import AsyncIterator, Iterable

from app.ai.config import get_model_config
from app.ai.providers import ChatEvent, ChatRequest, WebSearchResult, WebSource


class FakeChatProvider:
    def __init__(self, replies: Iterable[ChatEvent] = ()) -> None:
        self.replies = tuple(replies)
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        self.requests.append(request)
        for reply in self.replies:
            if isinstance(reply, Exception):
                raise reply
            yield reply


class FakeWebSearchProvider:
    def __init__(self, result: WebSearchResult | None = None) -> None:
        self.result = result or WebSearchResult(
            answer="Fake web answer.", sources=[WebSource(title="Example", url="https://example.com/a")]
        )
        self.queries: list[str] = []

    async def search(self, query: str) -> WebSearchResult:
        self.queries.append(query)
        return self.result


class SequencedChatProvider:
    """Plays one scripted reply per model call, for multi-round tool loops."""

    def __init__(self, rounds: Iterable[Iterable[ChatEvent]]) -> None:
        self.rounds = [tuple(item) for item in rounds]
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        self.requests.append(request)
        for reply in self.rounds[len(self.requests) - 1]:
            yield reply


class FakeEmbeddingProvider:
    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions or get_model_config().embedding_dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for value in texts:
            raw = bytearray()
            counter = 0
            while len(raw) < self.dimensions * 4:
                raw.extend(hashlib.sha256(f"{value}\0{counter}".encode()).digest())
                counter += 1
            vector = [int.from_bytes(raw[i:i + 4], "big") / 2147483648 - 1 for i in range(0, self.dimensions * 4, 4)]
            norm = math.sqrt(sum(item * item for item in vector)) or 1.0
            vectors.append([item / norm for item in vector])
        return vectors


class KeywordEmbeddingProvider:
    """Bag-of-words vectors intended for deterministic retrieval tests."""

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions or get_model_config().embedding_dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for value in texts:
            vector = [0.0] * self.dimensions
            for word in re.findall(r"\w+", value.lower()):
                index = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % self.dimensions
                vector[index] += 1.0
            norm = math.sqrt(sum(item * item for item in vector)) or 1.0
            vectors.append([item / norm for item in vector])
        return vectors
