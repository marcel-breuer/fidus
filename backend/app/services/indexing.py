"""Per-user document indexing operations."""

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.config import get_model_config
from app.ai.providers import EmbeddingProvider
from app.db.models import Chunk, Document, FileVersion, Node, User
from app.db.session import user_session
from app.services.extraction import ExtractionError, chunk_text, extract_text
from app.storage.base import Storage

logger = logging.getLogger(__name__)


async def enqueue_index_document(user_id: str, document_id: str) -> None:
    try:
        from app.worker.tasks import index_document_job

        await index_document_job.kiq(user_id, document_id)
    except Exception:
        logger.warning("Could not enqueue document indexing", extra={"user_id": user_id, "document_id": document_id})


async def create_pending_document(
    session: AsyncSession, user: User, node: Node, version: FileVersion
) -> Document:
    document = Document(
        user_id=user.id,
        node_id=node.id,
        version_id=version.id,
        source="upload",
        title=node.name,
        status="pending",
    )
    session.add(document)
    await session.flush()
    session.info.setdefault("after_commit", []).append(
        lambda: enqueue_index_document(user.id, document.id)
    )
    return document


async def mark_document_failed(user_id: str, document_id: str, code: str) -> None:
    async with user_session(user_id) as session:
        document = await session.scalar(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        if document is not None:
            await session.execute(delete(Chunk).where(Chunk.document_id == document.id, Chunk.user_id == user_id))
            document.status = "failed"
            document.error_code = code
            document.chunk_count = 0


async def index_document(
    user_id: str, document_id: str, storage: Storage, embedder: EmbeddingProvider
) -> None:
    async with user_session(user_id) as session:
        document = await session.scalar(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        if document is None:
            return
        version = (
            await session.scalar(
                select(FileVersion).where(FileVersion.id == document.version_id, FileVersion.user_id == user_id)
            )
            if document.version_id is not None
            else None
        )
        if version is None:
            source = None
        else:
            source = (version.storage_key, version.mime_type, version.id, document.node_id)
    if source is None:
        await mark_document_failed(user_id, document_id, "SOURCE_NOT_FOUND")
        return

    storage_key, mime_type, version_id, node_id = source
    content = bytearray()
    try:
        async for block in storage.open(storage_key):
            content.extend(block)
            if len(content) > 25 * 1024 * 1024:
                raise ExtractionError("CORRUPT_FILE")
        extracted = extract_text(mime_type, bytes(content))
        config = get_model_config().retrieval
        pieces = chunk_text(extracted, config.chunk_size_chars, config.chunk_overlap_chars)
        embeddings: list[list[float]] = []
        for start in range(0, len(pieces), 64):
            embeddings.extend(await embedder.embed(pieces[start:start + 64]))
        if len(embeddings) != len(pieces) or any(len(vector) != 1536 for vector in embeddings):
            raise ValueError("Invalid embedding response")
    except ExtractionError as exc:
        await mark_document_failed(user_id, document_id, exc.code)
        return
    except Exception:
        await mark_document_failed(user_id, document_id, "INDEXING_FAILED")
        return

    async with user_session(user_id) as session:
        document = await session.scalar(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        if document is None or document.version_id != version_id:
            return
        await session.execute(delete(Chunk).where(Chunk.document_id == document.id, Chunk.user_id == user_id))
        # A new version invalidates prior content immediately after the new index is ready.
        if node_id:
            latest_version = await session.scalar(
                select(FileVersion.id)
                .where(FileVersion.node_id == node_id, FileVersion.user_id == user_id)
                .order_by(FileVersion.version.desc())
                .limit(1)
            )
            if latest_version == version_id:
                stale_ids = select(Document.id).where(
                    Document.node_id == node_id,
                    Document.user_id == user_id,
                    Document.id != document.id,
                )
                await session.execute(delete(Chunk).where(Chunk.document_id.in_(stale_ids), Chunk.user_id == user_id))
        session.add_all(
            Chunk(user_id=user_id, document_id=document.id, position=position, content=piece, embedding=vector)
            for position, (piece, vector) in enumerate(zip(pieces, embeddings, strict=True))
        )
        document.content = extracted
        document.status = "ready"
        document.error_code = None
        document.chunk_count = len(pieces)


async def latest_document(session: AsyncSession, user: User, node_id: str) -> Document | None:
    return await session.scalar(
        select(Document)
        .join(FileVersion, Document.version_id == FileVersion.id)
        .where(Document.user_id == user.id, Document.node_id == node_id)
        .order_by(FileVersion.version.desc())
        .limit(1)
    )


async def retry_latest_document(session: AsyncSession, user: User, node_id: str) -> Document | None:
    document = await latest_document(session, user, node_id)
    if document is None:
        return None
    document.status = "pending"
    document.error_code = None
    session.info.setdefault("after_commit", []).append(
        lambda: enqueue_index_document(user.id, document.id)
    )
    return document


async def index_document_text(user_id: str, document_id: str, embedder: EmbeddingProvider) -> None:
    """Chunk, embed and store the text already held by a document (memo transcripts)."""
    async with user_session(user_id) as session:
        document = await session.scalar(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        content = document.content if document is not None else None
    if not content:
        await mark_document_failed(user_id, document_id, "SOURCE_NOT_FOUND")
        return
    try:
        config = get_model_config().retrieval
        pieces = chunk_text(content, config.chunk_size_chars, config.chunk_overlap_chars)
        embeddings: list[list[float]] = []
        for start in range(0, len(pieces), 64):
            embeddings.extend(await embedder.embed(pieces[start:start + 64]))
        if len(embeddings) != len(pieces) or any(len(vector) != 1536 for vector in embeddings):
            raise ValueError("Invalid embedding response")
    except Exception:
        await mark_document_failed(user_id, document_id, "INDEXING_FAILED")
        return
    async with user_session(user_id) as session:
        document = await session.scalar(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
        if document is None:
            return
        await session.execute(delete(Chunk).where(Chunk.document_id == document.id, Chunk.user_id == user_id))
        session.add_all(
            Chunk(user_id=user_id, document_id=document.id, position=position, content=piece, embedding=vector)
            for position, (piece, vector) in enumerate(zip(pieces, embeddings, strict=True))
        )
        document.status = "ready"
        document.error_code = None
        document.chunk_count = len(pieces)
