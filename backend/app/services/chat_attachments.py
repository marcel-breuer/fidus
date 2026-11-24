"""Private, bounded storage and provider payloads for chat attachments."""

import base64
import json
import unicodedata
from collections.abc import AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import new_id
from app.db.models import Conversation, Message, MessageAttachment, User
from app.services.extraction import ExtractionError, extract_text
from app.storage.base import Storage, StorageTooLarge

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 5
ALLOWED_TYPES = {
    "application/pdf", "text/plain", "text/markdown", "image/png", "image/jpeg", "image/webp"
}


class AttachmentError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _filename(value: str) -> str:
    name = value.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch) != "Cc").strip()
    if not name or len(name) > 255:
        raise AttachmentError("INVALID_NAME")
    return name


def _validate_content(mime_type: str, content: bytes) -> str | None:
    if mime_type not in ALLOWED_TYPES:
        raise AttachmentError("UNSUPPORTED_TYPE")
    if mime_type == "application/pdf" and not content.startswith(b"%PDF-"):
        raise AttachmentError("UNSUPPORTED_TYPE")
    if mime_type == "image/png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AttachmentError("UNSUPPORTED_TYPE")
    if mime_type == "image/jpeg" and not content.startswith(b"\xff\xd8\xff"):
        raise AttachmentError("UNSUPPORTED_TYPE")
    if mime_type == "image/webp" and not (content.startswith(b"RIFF") and content[8:12] == b"WEBP"):
        raise AttachmentError("UNSUPPORTED_TYPE")
    if mime_type in {"text/plain", "text/markdown"}:
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise AttachmentError("UNSUPPORTED_TYPE") from exc
        if b"\x00" in content:
            raise AttachmentError("UNSUPPORTED_TYPE")
        return content.decode("utf-8-sig")[:100_000]
    if mime_type.startswith("image/"):
        return None
    try:
        return extract_text(mime_type, content)[:100_000]
    except ExtractionError as exc:
        if exc.code == "EMPTY_TEXT":
            return ""
        raise AttachmentError(exc.code) from exc


async def _bytes(stream: AsyncIterator[bytes]) -> bytes:
    output = bytearray()
    async for chunk in stream:
        output.extend(chunk)
        if len(output) > MAX_ATTACHMENT_BYTES:
            raise AttachmentError("FILE_TOO_LARGE")
    return bytes(output)


async def upload(
    session: AsyncSession, storage: Storage, user: User, conversation_id: str,
    filename: str, mime_type: str, content: bytes,
) -> MessageAttachment:
    conversation = await session.scalar(select(Conversation.id).where(
        Conversation.id == conversation_id, Conversation.user_id == user.id, Conversation.deleted_at.is_(None)
    ))
    if conversation is None:
        raise AttachmentError("CONVERSATION_NOT_FOUND")
    pending_count = await session.scalar(select(func.count()).select_from(MessageAttachment).where(
        MessageAttachment.user_id == user.id,
        MessageAttachment.conversation_id == conversation_id,
        MessageAttachment.message_id.is_(None),
    ))
    if pending_count is not None and pending_count >= MAX_ATTACHMENTS_PER_MESSAGE:
        raise AttachmentError("TOO_MANY_ATTACHMENTS")
    if not content or len(content) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError("FILE_TOO_LARGE" if content else "EMPTY_FILE")
    extracted = _validate_content(mime_type, content)
    attachment_id = new_id()
    key = f"{user.id}/{attachment_id}"

    async def chunks() -> AsyncIterator[bytes]:
        yield content

    try:
        stored_size = await storage.put(key, chunks())
    except StorageTooLarge as exc:
        raise AttachmentError("FILE_TOO_LARGE") from exc
    item = MessageAttachment(
        id=attachment_id, user_id=user.id, conversation_id=conversation_id, filename=_filename(filename),
        mime_type=mime_type, storage_key=key, size_bytes=stored_size, extracted_text=extracted,
    )
    session.add(item)
    session.info.setdefault("file_storage_cleanup", []).append((storage, key))
    await session.flush()
    return item


async def bind_and_load(
    session: AsyncSession, storage: Storage, user: User, conversation_id: str,
    message: Message, attachment_ids: list[str],
) -> tuple[str, list[str], list[dict]]:
    if len(attachment_ids) > MAX_ATTACHMENTS_PER_MESSAGE or len(set(attachment_ids)) != len(attachment_ids):
        raise AttachmentError("INVALID_ATTACHMENTS")
    if not attachment_ids:
        return message.content, [], []
    rows = list((await session.scalars(select(MessageAttachment).where(
        MessageAttachment.id.in_(attachment_ids), MessageAttachment.user_id == user.id,
        MessageAttachment.conversation_id == conversation_id, MessageAttachment.message_id.is_(None),
    ))).all())
    if len(rows) != len(attachment_ids):
        raise AttachmentError("ATTACHMENT_NOT_FOUND")
    # Preserve the caller's order, while all rows remain owner-scoped by the service and RLS.
    by_id = {row.id: row for row in rows}
    ordered = [by_id[item_id] for item_id in attachment_ids]
    blocks: list[dict[str, str]] = []
    images: list[str] = []
    sources: list[dict] = []
    for item in ordered:
        item.message = message
        sources.append({
            "id": item.id, "type": "attachment", "filename": item.filename, "mime_type": item.mime_type,
            "size_bytes": item.size_bytes, "ref": len(sources) + 1,
        })
        if item.extracted_text:
            blocks.append({"filename": item.filename, "text": item.extracted_text})
        if item.mime_type.startswith("image/"):
            data = await _bytes(storage.open(item.storage_key))
            encoded = base64.b64encode(data).decode("ascii")
            images.append(f"data:{item.mime_type};base64,{encoded}")
    context = json.dumps(blocks, ensure_ascii=False)
    content = (
        f"{message.content}\n\nUntrusted attachment text follows:\n"
        f"<untrusted_attachments>{context}</untrusted_attachments>"
        if blocks
        else message.content
    )
    return content, images, sources


async def validate_ids(
    session: AsyncSession, user: User, conversation_id: str, attachment_ids: list[str]
) -> None:
    if len(attachment_ids) > MAX_ATTACHMENTS_PER_MESSAGE or len(set(attachment_ids)) != len(attachment_ids):
        raise AttachmentError("INVALID_ATTACHMENTS")
    if not attachment_ids:
        return
    rows = (await session.scalars(select(MessageAttachment.id).where(
        MessageAttachment.id.in_(attachment_ids), MessageAttachment.user_id == user.id,
        MessageAttachment.conversation_id == conversation_id, MessageAttachment.message_id.is_(None),
    ))).all()
    if len(attachment_ids) != len(rows):
        raise AttachmentError("ATTACHMENT_NOT_FOUND")
