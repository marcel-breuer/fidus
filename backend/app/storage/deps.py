from collections.abc import AsyncIterator

from app.config import get_settings
from app.storage.base import Storage
from app.storage.local import LocalStorage

_storage: LocalStorage | None = None


async def get_storage() -> AsyncIterator[Storage]:
    global _storage
    if _storage is None:
        _storage = LocalStorage(get_settings().storage_path)
    yield _storage
