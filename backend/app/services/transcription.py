"""Memo transcription: split audio with ffmpeg, transcribe the segments, store a searchable document."""

import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import NamedTuple

from fastapi import HTTPException
from sqlalchemy import select

from app.ai.providers import EmbeddingProvider, TranscriptionProvider
from app.db.models import Document, Memo
from app.db.session import user_session
from app.services import usage
from app.services.indexing import index_document_text
from app.storage.base import Storage

logger = logging.getLogger(__name__)

# 10 minutes of 32 kbit/s mono MP3 is about 2.4 MB, far below the provider's 25 MB request limit,
# so any recording up to the upload cap yields segments that fit.
SEGMENT_SECONDS = 600
FFMPEG_TIMEOUT_SECONDS = 900
SEGMENT_BITRATE = 32_000  # bits per second, matches `-b:a 32k` below

Segmenter = Callable[[bytes, str], Awaitable[list[bytes]]]


class ShortTranscription(NamedTuple):
    text: str
    seconds: int


class TranscriptionError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


async def split_with_ffmpeg(
    data: bytes,
    extension: str,
    segment_seconds: int = SEGMENT_SECONDS,
    max_duration_seconds: int | None = None,
) -> list[bytes]:
    """Re-encode to mono 16 kHz MP3 and cut into fixed-length segments."""
    with tempfile.TemporaryDirectory(prefix="fidus-audio-") as directory:
        root = Path(directory)
        source = root / f"input{extension}"
        source.write_bytes(data)
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-vn",
                "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k",
                *(["-t", str(max_duration_seconds)] if max_duration_seconds is not None else []),
                "-f", "segment", "-segment_time", str(segment_seconds), "-reset_timestamps", "1",
                str(root / "segment_%05d.mp3"),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise TranscriptionError("FFMPEG_UNAVAILABLE") from exc
        try:
            code = await asyncio.wait_for(process.wait(), FFMPEG_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise TranscriptionError("AUDIO_PROCESSING_FAILED") from exc
        if code != 0:
            raise TranscriptionError("CORRUPT_AUDIO")
        segments = [path.read_bytes() for path in sorted(root.glob("segment_*.mp3"))]
    if not segments or not any(segments):
        raise TranscriptionError("CORRUPT_AUDIO")
    return segments


def audio_seconds(segments: list[bytes]) -> int:
    """Duration of the re-encoded segments. They are constant-bitrate MP3, so size maps to time."""
    return round(sum(len(segment) for segment in segments) * 8 / SEGMENT_BITRATE)


async def transcribe_segments(
    data: bytes,
    extension: str,
    transcriber: TranscriptionProvider,
    segmenter: Segmenter = split_with_ffmpeg,
    language: str | None = None,
) -> str:
    return (await _transcribe(data, extension, transcriber, segmenter, language))[0]


async def transcribe_short_clip(
    data: bytes,
    filename: str,
    transcriber: TranscriptionProvider,
    max_seconds: int,
    language: str | None = None,
    segmenter: Segmenter = split_with_ffmpeg,
) -> ShortTranscription:
    """Transcribe one bounded clip without creating a memo or storing its transcript."""
    from app.services.audio_formats import TYPES, matches_signature

    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    extension = ("." + name.rsplit(".", 1)[-1]).lower() if "." in name else ""
    if extension not in TYPES or not matches_signature(extension, data[:12]):
        raise TranscriptionError("UNSUPPORTED_TYPE")
    if segmenter is split_with_ffmpeg:
        segments = await split_with_ffmpeg(data, extension, max_duration_seconds=max_seconds + 1)
    else:
        segments = await segmenter(data, extension)
    duration = sum(len(segment) for segment in segments) * 8 / SEGMENT_BITRATE
    seconds = round(duration)
    if seconds < 1:
        raise TranscriptionError("CORRUPT_AUDIO")
    if duration > max_seconds:
        raise TranscriptionError("CLIP_TOO_LONG")
    parts: list[str] = []
    for index, segment in enumerate(segments):
        try:
            parts.append(await transcriber.transcribe(segment, f"segment-{index:05d}.mp3", language))
        except Exception as exc:
            raise TranscriptionError("TRANSCRIPTION_FAILED") from exc
    text = " ".join(part for part in parts if part).strip()
    if not text:
        raise TranscriptionError("EMPTY_TRANSCRIPT")
    return ShortTranscription(text, seconds)


async def _transcribe(
    data: bytes,
    extension: str,
    transcriber: TranscriptionProvider,
    segmenter: Segmenter,
    language: str | None,
) -> tuple[str, int]:
    """Transcript plus the seconds of audio sent to the provider."""
    segments = await segmenter(data, extension)
    parts: list[str] = []
    for index, segment in enumerate(segments):
        try:
            parts.append(await transcriber.transcribe(segment, f"segment-{index:05d}.mp3", language))
        except Exception as exc:  # provider errors may carry request details; keep only a stable code
            raise TranscriptionError("TRANSCRIPTION_FAILED") from exc
    text = " ".join(part for part in parts if part).strip()
    if not text:
        raise TranscriptionError("EMPTY_TRANSCRIPT")
    return text, audio_seconds(segments)


async def _fail(user_id: str, memo_id: str, code: str) -> None:
    async with user_session(user_id) as session:
        memo = await session.scalar(select(Memo).where(Memo.id == memo_id, Memo.user_id == user_id))
        if memo is not None:
            memo.status = "failed"
            memo.error_code = code


async def process_memo(
    user_id: str,
    memo_id: str,
    storage: Storage,
    transcriber: TranscriptionProvider | None,
    embedder: EmbeddingProvider | None,
    segmenter: Segmenter = split_with_ffmpeg,
) -> None:
    """Transcribe a memo (unless its transcript already exists) and index the transcript."""
    async with user_session(user_id) as session:
        memo = await session.scalar(
            select(Memo)
            .where(Memo.id == memo_id, Memo.user_id == user_id)
            .with_for_update()
        )
        if memo is None:
            return
        if memo.status == "transcribing":
            return
        existing = (
            await session.scalar(select(Document).where(Document.id == memo.document_id, Document.user_id == user_id))
            if memo.document_id
            else None
        )
        has_transcript = existing is not None and bool(existing.content)
        if not has_transcript:
            memo.status = "transcribing"
            memo.error_code = None
        audio_key, extension, language = memo.audio_key, _extension(memo.mime_type), memo.language
        document_id = existing.id if existing is not None else None
        title = memo.title

    if not has_transcript:
        if transcriber is None:
            await _fail(user_id, memo_id, "AI_NOT_CONFIGURED")
            return
        try:
            content = bytearray()
            async for block in storage.open(audio_key):
                content.extend(block)
            text, seconds = await _transcribe(bytes(content), extension, transcriber, segmenter, language)
        except TranscriptionError as exc:
            await _fail(user_id, memo_id, exc.code)
            return
        except Exception:
            logger.warning("Memo transcription failed", extra={"user_id": user_id, "memo_id": memo_id})
            await _fail(user_id, memo_id, "TRANSCRIPTION_FAILED")
            return
        async with user_session(user_id) as session:
            memo = await session.scalar(select(Memo).where(Memo.id == memo_id, Memo.user_id == user_id))
            if memo is None:
                return
            document = Document(
                user_id=user_id, source="memo", title=title, content=text, status="pending"
            )
            session.add(document)
            await session.flush()
            memo.document_id = document.id
            memo.status = "ready"
            memo.error_code = None
            document_id = document.id
            await usage.add(session, user_id, {usage.TRANSCRIPTION_SECONDS: seconds})

    assert document_id is not None
    if embedder is None:
        from app.services.indexing import mark_document_failed

        await mark_document_failed(user_id, document_id, "AI_NOT_CONFIGURED")
        return
    await index_document_text(user_id, document_id, embedder)


async def process_memo_job(
    user_id: str,
    memo_id: str,
    storage: Storage | None = None,
    transcriber: TranscriptionProvider | None = None,
    embedder: EmbeddingProvider | None = None,
    segmenter: Segmenter = split_with_ffmpeg,
) -> None:
    """Worker entry: honours module enablement and resolves providers from configuration."""
    from app.ai.deps import get_embedding_provider, get_transcription_provider
    from app.storage.deps import build_storage
    from app.worker.module_guard import ensure_module_enabled

    try:
        await ensure_module_enabled("audio")
    except RuntimeError as exc:
        if str(exc) != "MODULE_DISABLED":
            raise
        return
    if transcriber is None:
        try:
            transcriber = get_transcription_provider()
        except HTTPException:
            transcriber = None
    if embedder is None:
        try:
            embedder = get_embedding_provider()
        except HTTPException:
            embedder = None
    await process_memo(user_id, memo_id, storage or build_storage(), transcriber, embedder, segmenter)


def _extension(mime_type: str) -> str:
    from app.services.audio_formats import extension_for_mime

    return extension_for_mime(mime_type)
