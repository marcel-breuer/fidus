from collections.abc import AsyncIterator

from app.config import get_settings
from app.storage.base import Storage
from app.storage.local import LocalStorage

# Upper bound for any stored object; each module enforces its own, lower limits.
MAX_BLOB_BYTES = 100 * 1024 * 1024
_storage: LocalStorage | None = None


def build_storage() -> LocalStorage:
    global _storage
    if _storage is None:
        _storage = LocalStorage(get_settings().storage_path, max_bytes=MAX_BLOB_BYTES)
    return _storage


async def get_storage() -> AsyncIterator[Storage]:
    yield build_storage()
