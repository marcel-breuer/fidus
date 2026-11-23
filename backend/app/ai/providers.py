from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class ChatMessage:
    """A history item. An assistant item may echo a `tool_call`; a `tool` item answers
    one through `tool_call_id` and carries the tool output as content."""

    role: str
    content: str
    tool_call: ToolCall | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, object]


@dataclass(frozen=True)
class ChatRequest:
    system: str | None
    messages: list[ChatMessage]
    tools: list[ToolSpec]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Completed:
    usage: Usage


type ChatEvent = TextDelta | ToolCall | Completed


class ChatProvider(Protocol):
    def stream(self, request: ChatRequest) -> AsyncIterator[ChatEvent]: ...


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class WebSource:
    title: str
    url: str


@dataclass(frozen=True)
class WebSearchResult:
    answer: str
    sources: list[WebSource]


class WebSearchProvider(Protocol):
    """Web search behind a service boundary. Results are untrusted content."""

    async def search(self, query: str) -> WebSearchResult: ...
