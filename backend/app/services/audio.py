"""Per-user voice memo operations shared by REST routes and the worker."""

import logging
import unicodedata
from collections.abc import AsyncIterator
from typing import NamedTuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers import SpeechProvider
from app.db.base import new_id
from app.db.models import Chunk, Document, Memo, User
from app.services.audio_formats import TYPES as _TYPES
from app.services.audio_formats import matches_signature as _matches_signature
from app.services.extraction import chunk_text
from app.services.speech import MAX_SPEECH_CHARS, SPEECH_CHUNK_CHARS
from app.services.speech import join_wav as _join_wav
from app.storage.base import Storage, StorageTooLarge

logger = logging.getLogger(__name__)

MAX_MEMO_BYTES = 100 * 1024 * 1024

class AudioError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AudioDownload(NamedTuple):
    memo: Memo
    stream: AsyncIterator[bytes]


def _clean(value: str, limit: int) -> str:
    cleaned = "".join(c for c in value if unicodedata.category(c) != "Cc").strip()
    return cleaned[:limit]


async def create_memo(
    session: AsyncSession,
    storage: Storage,
    user: User,
    filename: str,
    content: AsyncIterator[bytes],
    title: str | None = None,
    language: str | None = None,
) -> Memo:
    name = _clean(filename.replace("\\", "/").split("/")[-1], 255)
    extension = ("." + name.rsplit(".", 1)[-1]).lower() if "." in name else ""
    if extension not in _TYPES:
        raise AudioError("UNSUPPORTED_TYPE")
    if language is not None and not (language.isalpha() and 2 <= len(language) <= 3):
        raise AudioError("INVALID_LANGUAGE")
    clean_title = _clean(title or "", 255) or _clean(name.rsplit(".", 1)[0], 255) or "Memo"
    head = bytearray()
    seen = 0

    async def checked() -> AsyncIterator[bytes]:
        nonlocal seen
        async for chunk in content:
            seen += len(chunk)
            if seen > MAX_MEMO_BYTES:
                raise StorageTooLarge
            if len(head) < 12:
                head.extend(chunk[: 12 - len(head)])
            yield chunk
        if not _matches_signature(extension, bytes(head)):
            raise AudioError("UNSUPPORTED_TYPE")

    key = f"{user.id}/{new_id()}"
    try:
        size = await storage.put(key, checked())
        session.info.setdefault("file_storage_cleanup", []).append((storage, key))
        if size == 0:
            raise AudioError("EMPTY_FILE")
        memo = Memo(
            user_id=user.id,
            title=clean_title,
            status="pending",
            audio_key=key,
            mime_type=_TYPES[extension],
            size_bytes=size,
            language=language.lower() if language else None,
        )
        session.add(memo)
        await session.flush()
    except BaseException:
        if await storage.exists(key):
            await storage.delete(key)
        raise
    session.info.setdefault("after_commit", []).append(lambda: enqueue_memo(user.id, memo.id))
    return memo


async def enqueue_memo(user_id: str, memo_id: str) -> None:
    try:
        from app.worker.tasks import transcribe_memo_job

        await transcribe_memo_job.kiq(user_id, memo_id)
    except Exception:
        logger.warning("Could not enqueue memo transcription", extra={"user_id": user_id, "memo_id": memo_id})


async def list_memos(session: AsyncSession, user: User) -> list[tuple[Memo, Document | None]]:
    rows = await session.execute(
        select(Memo, Document)
        .outerjoin(Document, Document.id == Memo.document_id)
        .where(Memo.user_id == user.id)
        .order_by(Memo.created_at.desc(), Memo.id.desc())
    )
    return [(memo, document) for memo, document in rows.all()]


async def get_memo(session: AsyncSession, user: User, memo_id: str) -> tuple[Memo, Document | None] | None:
    row = (
        await session.execute(
            select(Memo, Document)
            .outerjoin(Document, Document.id == Memo.document_id)
            .where(Memo.id == memo_id, Memo.user_id == user.id)
        )
    ).first()
    return None if row is None else (row[0], row[1])


async def rename_memo(session: AsyncSession, user: User, memo_id: str, title: str) -> Memo | None:
    clean_title = _clean(title, 255)
    if not clean_title:
        raise AudioError("INVALID_TITLE")
    found = await get_memo(session, user, memo_id)
    if found is None:
        return None
    memo, document = found
    memo.title = clean_title
    if document is not None:
        document.title = clean_title
    await session.flush()
    return memo


async def retry_memo(session: AsyncSession, user: User, memo_id: str) -> Memo | None:
    found = await get_memo(session, user, memo_id)
    if found is None:
        return None
    memo, document = found
    if memo.status == "failed":
        memo.status = "pending"
        memo.error_code = None
    elif document is not None and document.status == "failed":
        document.status = "pending"
        document.error_code = None
    else:
        raise AudioError("NOT_RETRYABLE")
    session.info.setdefault("after_commit", []).append(lambda: enqueue_memo(user.id, memo.id))
    return memo


async def delete_memo(session: AsyncSession, storage: Storage, user: User, memo_id: str) -> bool:
    found = await get_memo(session, user, memo_id)
    if found is None:
        return False
    memo, document = found
    keys = [memo.audio_key] + ([memo.speech_key] if memo.speech_key else [])
    if document is not None:
        await session.execute(delete(Chunk).where(Chunk.document_id == document.id, Chunk.user_id == user.id))
    await session.delete(memo)
    await session.flush()
    if document is not None:
        await session.delete(document)

    async def remove_blobs() -> None:
        for key in keys:
            await storage.delete(key)

    session.info.setdefault("after_commit", []).append(remove_blobs)
    return True


async def get_audio(session: AsyncSession, storage: Storage, user: User, memo_id: str) -> AudioDownload | None:
    found = await get_memo(session, user, memo_id)
    if found is None:
        return None
    return AudioDownload(found[0], storage.open(found[0].audio_key))


async def get_speech(
    session: AsyncSession,
    storage: Storage,
    user: User,
    memo_id: str,
    speech: SpeechProvider,
) -> AudioDownload | None:
    """Speech for the memo transcript, generated once and cached in storage."""
    found = await get_memo(session, user, memo_id)
    if found is None:
        return None
    memo, document = found
    if memo.speech_key and await storage.exists(memo.speech_key):
        return AudioDownload(memo, storage.open(memo.speech_key))
    if document is None or not document.content:
        raise AudioError("NO_TRANSCRIPT")
    if len(document.content) > MAX_SPEECH_CHARS:
        raise AudioError("TEXT_TOO_LONG")
    pieces = chunk_text(document.content, SPEECH_CHUNK_CHARS, 0)
    try:
        wav = _join_wav([await speech.synthesize(piece) for piece in pieces])
    except Exception as exc:
        logger.warning("Speech synthesis failed", extra={"user_id": user.id, "memo_id": memo.id})
        raise AudioError("SPEECH_FAILED") from exc

    async def once() -> AsyncIterator[bytes]:
        yield wav

    key = f"{user.id}/{new_id()}"
    await storage.put(key, once())
    session.info.setdefault("file_storage_cleanup", []).append((storage, key))
    previous = memo.speech_key
    memo.speech_key = key
    await session.flush()
    if previous:
        await storage.delete(previous)
    return AudioDownload(memo, storage.open(key))
