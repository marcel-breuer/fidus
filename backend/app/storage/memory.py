from collections.abc import AsyncIterator

from app.storage.base import StorageTooLarge


class MemoryStorage:
    def __init__(self, max_bytes: int = 25 * 1024 * 1024) -> None:
        self.max_bytes = max_bytes
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, stream: AsyncIterator[bytes]) -> int:
        chunks: list[bytes] = []
        size = 0
        async for chunk in stream:
            size += len(chunk)
            if size > self.max_bytes:
                raise StorageTooLarge
            chunks.append(chunk)
        self.objects[key] = b"".join(chunks)
        return size

    async def open(self, key: str) -> AsyncIterator[bytes]:
        data = self.objects[key]
        for offset in range(0, len(data), 1024 * 1024):
            yield data[offset : offset + 1024 * 1024]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objects
