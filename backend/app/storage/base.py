from collections.abc import AsyncIterator
from typing import Protocol


class StorageTooLarge(Exception):
    """Raised when a streamed object exceeds the configured limit."""


class Storage(Protocol):
    async def put(self, key: str, stream: AsyncIterator[bytes]) -> int: ...

    def open(self, key: str) -> AsyncIterator[bytes]: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...
