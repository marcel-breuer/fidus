import hashlib
import tempfile
import unicodedata
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import NamedTuple
from zipfile import BadZipFile, ZipFile

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import new_id
from app.db.models import FileVersion, Node, User
from app.services.indexing import create_pending_document
from app.storage.base import Storage, StorageTooLarge

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".docx"}


class FilesError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Download(NamedTuple):
    version: FileVersion
    stream: AsyncIterator[bytes]


def sanitize_name(value: str) -> str:
    name = value.replace("\\", "/").split("/")[-1]
    name = "".join(character for character in name if unicodedata.category(character) != "Cc").strip()
    if not name or name in {".", ".."} or len(name) > 255:
        raise FilesError("INVALID_NAME")
    return name


async def _parent(session: AsyncSession, user: User, parent_id: str | None) -> Node | None:
    if parent_id is None:
        return None
    parent = await session.scalar(
        select(Node).where(
            Node.id == parent_id,
            Node.user_id == user.id,
            Node.kind == "folder",
            Node.deleted_at.is_(None),
        )
    )
    if parent is None:
        raise FilesError("PARENT_NOT_FOUND")
    return parent


async def list_children(session: AsyncSession, user: User, parent_id: str | None) -> list[Node]:
    if parent_id is not None:
        await _parent(session, user, parent_id)
    return list(
        (
            await session.scalars(
                select(Node)
                .where(
                    Node.user_id == user.id,
                    Node.parent_id.is_(None) if parent_id is None else Node.parent_id == parent_id,
                    Node.deleted_at.is_(None),
                )
                .order_by(Node.kind.desc(), Node.name.collate("C"), Node.id)
            )
        ).all()
    )


async def create_folder(
    session: AsyncSession, user: User, name: str, parent_id: str | None
) -> Node:
    clean = sanitize_name(name)
    await _parent(session, user, parent_id)
    node = Node(user_id=user.id, parent_id=parent_id, kind="folder", name=clean)
    session.add(node)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise FilesError("NAME_CONFLICT") from exc
    return node


async def upload_file(
    session: AsyncSession,
    storage: Storage,
    user: User,
    parent_id: str | None,
    filename: str,
    content: AsyncIterator[bytes],
    declared_mime: str | None = None,
) -> tuple[Node, FileVersion]:
    del declared_mime  # Client supplied MIME values are untrusted.
    name = sanitize_name(filename)
    extension = ("." + name.rsplit(".", 1)[-1]).lower() if "." in name else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise FilesError("UNSUPPORTED_TYPE")
    await _parent(session, user, parent_id)
    node = await session.scalar(
        select(Node).where(
            Node.user_id == user.id,
            Node.parent_id.is_(None) if parent_id is None else Node.parent_id == parent_id,
            Node.name == name,
            Node.deleted_at.is_(None),
        )
    )
    if node is not None and node.kind != "file":
        raise FilesError("NAME_CONFLICT")

    blob_id = new_id()
    storage_key = f"{user.id}/{blob_id}"
    digest = hashlib.sha256()
    text_decoder = None
    if extension in {".txt", ".md", ".markdown"}:
        import codecs

        text_decoder = codecs.getincrementaldecoder("utf-8")("strict")
    prefix = bytearray()
    size_seen = 0

    async def checked() -> AsyncIterator[bytes]:
        nonlocal size_seen
        async for chunk in content:
            size_seen += len(chunk)
            if size_seen > MAX_UPLOAD_BYTES:
                raise StorageTooLarge
            digest.update(chunk)
            if len(prefix) < 8:
                prefix.extend(chunk[: 8 - len(prefix)])
            if text_decoder is not None:
                if b"\x00" in chunk:
                    raise FilesError("UNSUPPORTED_TYPE")
                try:
                    text_decoder.decode(chunk, final=False)
                except UnicodeDecodeError as exc:
                    raise FilesError("UNSUPPORTED_TYPE") from exc
            yield chunk
        if text_decoder is not None:
            try:
                text_decoder.decode(b"", final=True)
            except UnicodeDecodeError as exc:
                raise FilesError("UNSUPPORTED_TYPE") from exc
        if extension == ".pdf" and not prefix.startswith(b"%PDF-"):
            raise FilesError("UNSUPPORTED_TYPE")
        if extension == ".docx" and not prefix.startswith(b"PK\x03\x04"):
            raise FilesError("UNSUPPORTED_TYPE")

    try:
        size = await storage.put(storage_key, checked())
        cleanup = session.info.setdefault("file_storage_cleanup", [])
        cleanup.append((storage, storage_key))
        if size != size_seen:
            raise RuntimeError("Storage size did not match uploaded bytes")
        if extension == ".docx":
            with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as archive:
                async for chunk in storage.open(storage_key):
                    archive.write(chunk)
                archive.seek(0)
                try:
                    with ZipFile(archive) as document:
                        if "[Content_Types].xml" not in document.namelist():
                            raise FilesError("UNSUPPORTED_TYPE")
                except BadZipFile as exc:
                    raise FilesError("UNSUPPORTED_TYPE") from exc
        if node is None:
            node = Node(user_id=user.id, parent_id=parent_id, kind="file", name=name)
            session.add(node)
            await session.flush()
            version_number = 1
        else:
            latest = await session.scalar(
                select(FileVersion.version)
                .where(FileVersion.node_id == node.id, FileVersion.user_id == user.id)
                .order_by(FileVersion.version.desc())
                .limit(1)
            )
            version_number = (latest or 0) + 1
            node.updated_at = datetime.now(UTC)
        version = FileVersion(
            user_id=user.id,
            node_id=node.id,
            version=version_number,
            storage_key=storage_key,
            size_bytes=size,
            mime_type={
                ".txt": "text/plain; charset=utf-8",
                ".md": "text/markdown; charset=utf-8",
                ".markdown": "text/markdown; charset=utf-8",
                ".pdf": "application/pdf",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }[extension],
            sha256=digest.hexdigest(),
        )
        session.add(version)
        await session.flush()
        await create_pending_document(session, user, node, version)
        return node, version
    except BaseException:
        if await storage.exists(storage_key):
            await storage.delete(storage_key)
        cleanup_items = session.info.get("file_storage_cleanup", [])
        session.info["file_storage_cleanup"] = [
            item for item in cleanup_items if item != (storage, storage_key)
        ]
        raise


TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}


def _text_extension(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1]).lower() if "." in name else ""


async def _text_chunks(content: str) -> AsyncIterator[bytes]:
    yield content.encode("utf-8")


async def create_text_file(
    session: AsyncSession, storage: Storage, user: User, parent_id: str | None, name: str, content: str
) -> tuple[Node, FileVersion]:
    """Create a new text file for the agent. Unlike an upload, an existing name is a conflict."""
    if "/" in name or "\\" in name:
        raise FilesError("INVALID_NAME")
    clean = sanitize_name(name)
    if _text_extension(clean) not in TEXT_EXTENSIONS:
        raise FilesError("UNSUPPORTED_TYPE")
    await _parent(session, user, parent_id)
    taken = await session.scalar(
        select(Node.id).where(
            Node.user_id == user.id,
            Node.parent_id.is_(None) if parent_id is None else Node.parent_id == parent_id,
            Node.name == clean,
            Node.deleted_at.is_(None),
        )
    )
    if taken is not None:
        raise FilesError("NAME_CONFLICT")
    return await upload_file(session, storage, user, parent_id, clean, _text_chunks(content))


async def update_text_file(
    session: AsyncSession, storage: Storage, user: User, node_id: str, content: str
) -> tuple[Node, FileVersion]:
    """Store a new version of one of the user's text files; the name and place stay unchanged."""
    node = await session.scalar(
        select(Node).where(
            Node.id == node_id, Node.user_id == user.id, Node.kind == "file", Node.deleted_at.is_(None)
        )
    )
    if node is None:
        raise FilesError("NODE_NOT_FOUND")
    if _text_extension(node.name) not in TEXT_EXTENSIONS:
        raise FilesError("UNSUPPORTED_TYPE")
    return await upload_file(session, storage, user, node.parent_id, node.name, _text_chunks(content))


async def rename_or_move(
    session: AsyncSession,
    user: User,
    node_id: str,
    *,
    name: str | None = None,
    parent_id: str | None = None,
    move_requested: bool = False,
) -> Node | None:
    node = await session.scalar(
        select(Node).where(Node.id == node_id, Node.user_id == user.id, Node.deleted_at.is_(None))
    )
    if node is None:
        return None
    if name is not None:
        node.name = sanitize_name(name)
    if move_requested:
        await _parent(session, user, parent_id)
        if node.kind == "folder" and parent_id is not None:
            descendants = text(
                "WITH RECURSIVE tree(id) AS ("
                "SELECT id FROM nodes WHERE id = :node_id AND user_id = :user_id AND deleted_at IS NULL "
                "UNION ALL SELECT child.id FROM nodes child JOIN tree ON child.parent_id = tree.id "
                "WHERE child.user_id = :user_id AND child.deleted_at IS NULL) SELECT id FROM tree"
            )
            result = await session.execute(descendants, {"node_id": node.id, "user_id": user.id})
            ids = {row[0] for row in result.all()}
            if parent_id in ids:
                raise FilesError("MOVE_CYCLE")
        node.parent_id = parent_id
    node.updated_at = datetime.now(UTC)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise FilesError("NAME_CONFLICT") from exc
    return node


async def soft_delete(session: AsyncSession, user: User, node_id: str) -> bool:
    node = await session.scalar(
        select(Node).where(Node.id == node_id, Node.user_id == user.id, Node.deleted_at.is_(None))
    )
    if node is None:
        return False
    now = datetime.now(UTC)
    await session.execute(
        text(
            "WITH RECURSIVE tree(id) AS (SELECT id FROM nodes WHERE id = :id AND user_id = :user_id "
            "UNION ALL SELECT child.id FROM nodes child JOIN tree ON child.parent_id = tree.id "
            "WHERE child.user_id = :user_id) UPDATE nodes SET deleted_at = :now, updated_at = :now "
            "WHERE id IN (SELECT id FROM tree) AND user_id = :user_id AND deleted_at IS NULL"
        ),
        {"id": node.id, "user_id": user.id, "now": now},
    )
    await session.execute(
        text(
            "WITH RECURSIVE tree(id) AS (SELECT id FROM nodes WHERE id = :id AND user_id = :user_id "
            "UNION ALL SELECT child.id FROM nodes child JOIN tree ON child.parent_id = tree.id "
            "WHERE child.user_id = :user_id) "
            "DELETE FROM documents WHERE user_id = :user_id AND node_id IN (SELECT id FROM tree)"
        ),
        {"id": node.id, "user_id": user.id},
    )
    return True


async def list_versions(session: AsyncSession, user: User, node_id: str) -> list[FileVersion] | None:
    node = await session.scalar(
        select(Node).where(
            Node.id == node_id, Node.user_id == user.id, Node.kind == "file", Node.deleted_at.is_(None)
        )
    )
    if node is None:
        return None
    return list(
        (
            await session.scalars(
                select(FileVersion)
                .where(FileVersion.node_id == node.id, FileVersion.user_id == user.id)
                .order_by(FileVersion.version.desc())
            )
        ).all()
    )


async def get_download(
    session: AsyncSession, storage: Storage, user: User, node_id: str, version: int | None = None
) -> Download | None:
    node = await session.scalar(
        select(Node).where(
            Node.id == node_id, Node.user_id == user.id, Node.kind == "file", Node.deleted_at.is_(None)
        )
    )
    if node is None:
        return None
    statement = select(FileVersion).where(FileVersion.node_id == node.id, FileVersion.user_id == user.id)
    if version is not None:
        statement = statement.where(FileVersion.version == version)
    row = await session.scalar(statement.order_by(FileVersion.version.desc()).limit(1))
    if row is None:
        return None
    return Download(row, storage.open(row.storage_key))
