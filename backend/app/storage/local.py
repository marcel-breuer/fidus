import asyncio
import os
import re
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from app.storage.base import StorageTooLarge

_KEY = re.compile(r"[A-Za-z0-9_-]{1,26}/[0-9A-HJKMNP-TV-Z]{26}\Z")


class LocalStorage:
    def __init__(self, root: str | Path, max_bytes: int = 25 * 1024 * 1024) -> None:
        self.root = Path(root).resolve()
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not _KEY.fullmatch(key):
            raise ValueError("Invalid storage key")
        path = self.root.joinpath(*key.split("/"))
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Invalid storage key")
        return path

    async def put(self, key: str, stream: AsyncIterator[bytes]) -> int:
        path = self._path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".upload-", dir=path.parent)
        size = 0
        try:
            with os.fdopen(descriptor, "wb") as target:
                async for chunk in stream:
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise StorageTooLarge
                    await asyncio.to_thread(target.write, chunk)
                await asyncio.to_thread(target.flush)
                await asyncio.to_thread(os.fsync, target.fileno())
            await asyncio.to_thread(os.replace, temporary, path)
            return size
        except BaseException:
            try:
                await asyncio.to_thread(os.unlink, temporary)
            except FileNotFoundError:
                pass
            raise

    async def open(self, key: str) -> AsyncIterator[bytes]:
        path = self._path(key)
        with path.open("rb") as source:
            while chunk := await asyncio.to_thread(source.read, 1024 * 1024):
                yield chunk

    async def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            await asyncio.to_thread(path.unlink)
        except FileNotFoundError:
            pass

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)
