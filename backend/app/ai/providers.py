from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


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
class ToolCall:
    id: str
    name: str
    arguments_json: str


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


class TranscriptionProvider(Protocol):
    async def transcribe(self, audio: bytes, filename: str, language: str | None = None) -> str: ...


class SpeechProvider(Protocol):
    async def synthesize(self, text: str) -> bytes:
        """Return a complete WAV file (24 kHz, 16-bit, mono) speaking `text` verbatim."""
        ...
