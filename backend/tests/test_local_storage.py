from collections.abc import AsyncIterator

import pytest

from app.storage.base import StorageTooLarge
from app.storage.local import LocalStorage

USER_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
BLOB_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


async def _chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


async def test_local_storage_writes_atomically_and_streams(tmp_path) -> None:
    storage = LocalStorage(tmp_path)
    key = f"{USER_ID}/{BLOB_ID}"
    assert await storage.put(key, _chunks(b"hello", b" world")) == 11
    assert await storage.exists(key)
    chunks = [chunk async for chunk in storage.open(key)]
    assert b"".join(chunks) == b"hello world"


async def test_local_storage_rejects_traversal_keys(tmp_path) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        await storage.put(f"{USER_ID}/../../outside", _chunks(b"unsafe"))
    with pytest.raises(ValueError):
        await storage.exists("../outside")


async def test_local_storage_enforces_limit_and_leaves_no_partial_file(tmp_path) -> None:
    storage = LocalStorage(tmp_path, max_bytes=3)
    key = f"{USER_ID}/{BLOB_ID}"
    with pytest.raises(StorageTooLarge):
        await storage.put(key, _chunks(b"12", b"34"))
    assert not await storage.exists(key)
    assert list(tmp_path.rglob(".upload-*")) == []
