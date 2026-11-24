"""Chat adapters over shared audio providers and storage."""

import logging
from collections.abc import AsyncIterator
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import SpeechProvider, TranscriptionProvider
from app.db.base import new_id
from app.db.models import Message, User
from app.services import usage
from app.services.extraction import chunk_text
from app.services.speech import MAX_SPEECH_CHARS, SPEECH_CHUNK_CHARS, join_wav
from app.services.transcription import TranscriptionError, transcribe_short_clip
from app.storage.base import Storage

logger = logging.getLogger(__name__)
MAX_DICTATION_BYTES = 10 * 1024 * 1024
MAX_DICTATION_SECONDS = 60


class ChatAudioError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SpeechDownload(NamedTuple):
    message: Message
    stream: AsyncIterator[bytes]


async def get_message_speech(
    session: AsyncSession,
    storage: Storage,
    user: User,
    conversation_id: str,
    message_id: str,
    speech: SpeechProvider,
) -> SpeechDownload | None:
    message = await session.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
            Message.user_id == user.id,
            Message.role == "assistant",
            Message.deleted_at.is_(None),
        )
    )
    if message is None:
        return None
    if message.speech_key and await storage.exists(message.speech_key):
        return SpeechDownload(message, storage.open(message.speech_key))
    if not message.content:
        raise ChatAudioError("NO_MESSAGE_CONTENT")
    if len(message.content) > MAX_SPEECH_CHARS:
        raise ChatAudioError("TEXT_TOO_LONG")
    try:
        pieces = chunk_text(message.content, SPEECH_CHUNK_CHARS, 0)
        output = join_wav([await speech.synthesize(piece) for piece in pieces])
    except Exception as exc:
        logger.warning("Chat speech synthesis failed", extra={"user_id": user.id, "message_id": message.id})
        raise ChatAudioError("SPEECH_FAILED") from exc

    async def once() -> AsyncIterator[bytes]:
        yield output

    key = f"{user.id}/{new_id()}"
    try:
        await storage.put(key, once())
    except Exception as exc:
        raise ChatAudioError("SPEECH_FAILED") from exc
    session.info.setdefault("file_storage_cleanup", []).append((storage, key))
    old_key = message.speech_key
    message.speech_key = key
    await session.flush()
    if old_key:
        session.info.setdefault("after_commit", []).append(lambda: storage.delete(old_key))
    return SpeechDownload(message, storage.open(key))


async def transcribe_dictation(
    user_id: str,
    data: bytes,
    filename: str,
    transcriber: TranscriptionProvider,
    language: str | None = None,
) -> str:
    if not data:
        raise ChatAudioError("EMPTY_FILE")
    if len(data) > MAX_DICTATION_BYTES:
        raise ChatAudioError("FILE_TOO_LARGE")
    if language is not None and not (language.isalpha() and 2 <= len(language) <= 3):
        raise ChatAudioError("INVALID_LANGUAGE")
    try:
        result = await transcribe_short_clip(
            data, filename, transcriber, MAX_DICTATION_SECONDS, language.lower() if language else None
        )
        await usage.record(user_id, **{usage.TRANSCRIPTION_SECONDS: result.seconds})
        return result.text
    except TranscriptionError as exc:
        raise ChatAudioError(exc.code) from exc


async def ensure_conversation_access(
    session: AsyncSession, user: User, conversation_id: str
) -> bool:
    from app.db.models import Conversation

    return await session.scalar(
        select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
            Conversation.deleted_at.is_(None),
        )
    ) is not None
