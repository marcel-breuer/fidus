from io import BytesIO
from zipfile import ZipFile

import httpx
import pytest

from app.services import files as files_service
from app.storage.memory import MemoryStorage
from tests.helpers import PASSWORD, register


async def _login(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""


async def _register_login(client: httpx.AsyncClient, email: str) -> str:
    result = await register(client, email)
    assert result.status_code == 201
    await _login(client, email)
    return result.json()["id"]


async def test_files_auth_module_guard_and_crud(client: httpx.AsyncClient, owner_engine) -> None:
    assert (await client.get("/api/v1/files/nodes")).status_code == 401
    await _register_login(client, "files-crud@example.com")
    missing_csrf = await client.post("/api/v1/files/folders", json={"name": "Denied"}, headers={"X-CSRF-Token": "bad"})
    assert missing_csrf.status_code == 403
    folder_response = await client.post("/api/v1/files/folders", json={"name": "Archive"})
    assert folder_response.status_code == 201
    folder = folder_response.json()
    assert (await client.post("/api/v1/files/folders", json={"name": "Archive"})).status_code == 409

    child = await client.post("/api/v1/files/folders", json={"name": "Nested", "parent_id": folder["id"]})
    assert child.status_code == 201
    listing = await client.get("/api/v1/files/nodes", params={"parent_id": folder["id"]})
    assert [item["name"] for item in listing.json()] == ["Nested"]
    assert (
        await client.patch(f"/api/v1/files/nodes/{child.json()['id']}", json={"name": "Renamed"})
    ).status_code == 200

    disabled = await client.put("/api/v1/admin/modules/files", json={"enabled": False})
    assert disabled.status_code == 200
    assert (await client.get("/api/v1/files/nodes")).status_code == 404
    assert (await client.put("/api/v1/admin/modules/files", json={"enabled": True})).status_code == 200


async def test_upload_versions_validation_download_and_subtree_delete(client: httpx.AsyncClient) -> None:
    await _register_login(client, "files-upload@example.com")
    folder = (await client.post("/api/v1/files/folders", json={"name": "Documents"})).json()
    uploaded = await client.post(
        "/api/v1/files/upload",
        data={"parent_id": folder["id"]},
        files={"file": ("notes.txt", b"first version", "text/plain")},
    )
    assert uploaded.status_code == 201
    node_id = uploaded.json()["id"]
    second = await client.post(
        "/api/v1/files/upload",
        data={"parent_id": folder["id"]},
        files={"file": ("notes.txt", b"second version", "application/octet-stream")},
    )
    assert second.status_code == 201 and second.json()["id"] == node_id
    versions = await client.get(f"/api/v1/files/nodes/{node_id}/versions")
    assert [item["version"] for item in versions.json()] == [2, 1]
    renamed = await client.patch(f"/api/v1/files/nodes/{node_id}", json={"name": "renamed.txt"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "renamed.txt"
    download = await client.get(f"/api/v1/files/nodes/{node_id}/download?version=1")
    assert download.content == b"first version"
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"

    bad_pdf = await client.post("/api/v1/files/upload", files={"file": ("bad.pdf", b"not pdf", "application/pdf")})
    assert bad_pdf.status_code == 415
    nul_text = await client.post("/api/v1/files/upload", files={"file": ("bad.txt", b"a\0b", "text/plain")})
    assert nul_text.status_code == 415
    binary_text = await client.post("/api/v1/files/upload", files={"file": ("bad.txt", b"\xff\xfe", "text/plain")})
    assert binary_text.status_code == 415
    exe = await client.post("/api/v1/files/upload", files={"file": ("bad.exe", b"data", "text/plain")})
    assert exe.status_code == 415
    fake_docx = await client.post(
        "/api/v1/files/upload", files={"file": ("bad.docx", b"PK\x03\x04not a zip", "application/zip")}
    )
    assert fake_docx.status_code == 415
    archive = BytesIO()
    with ZipFile(archive, "w") as document:
        document.writestr("[Content_Types].xml", "<Types/>")
    good_docx = await client.post(
        "/api/v1/files/upload", files={"file": ("good.docx", archive.getvalue(), "application/zip")}
    )
    assert good_docx.status_code == 201
    assert (
        await client.post("/api/v1/files/upload", files={"file": ("../../etc/passwd.txt", b"ok", "text/plain")})
    ).status_code == 201
    assert (await client.post("/api/v1/files/upload", files={"file": ("..", b"ok", "text/plain")})).status_code == 422

    disposable = await client.post("/api/v1/files/upload", files={"file": ("remove.md", b"remove", "text/markdown")})
    assert disposable.status_code == 201
    disposable_id = disposable.json()["id"]
    assert (await client.delete(f"/api/v1/files/nodes/{disposable_id}")).status_code == 204
    assert (await client.get(f"/api/v1/files/nodes/{disposable_id}/download")).status_code == 404

    assert (await client.delete(f"/api/v1/files/nodes/{folder['id']}")).status_code == 204
    assert [item["name"] for item in (await client.get("/api/v1/files/nodes")).json()] == ["good.docx", "passwd.txt"]
    assert (await client.get(f"/api/v1/files/nodes/{node_id}/versions")).status_code == 404


async def test_move_cycle_into_file_and_cross_user_routes(client: httpx.AsyncClient) -> None:
    await _register_login(client, "files-owner@example.com")
    root = (await client.post("/api/v1/files/folders", json={"name": "Root"})).json()
    child = (await client.post("/api/v1/files/folders", json={"name": "Child", "parent_id": root["id"]})).json()
    file = (await client.post("/api/v1/files/upload", files={"file": ("item.md", b"ok", "text/markdown")})).json()
    assert (await client.patch(f"/api/v1/files/nodes/{root['id']}", json={"parent_id": child["id"]})).status_code == 422
    moved = await client.patch(f"/api/v1/files/nodes/{file['id']}", json={"parent_id": child["id"]})
    assert moved.status_code == 200 and moved.json()["parent_id"] == child["id"]
    assert [item["name"] for item in (await client.get(f"/api/v1/files/nodes?parent_id={child['id']}")).json()] == [
        "item.md"
    ]
    assert (await client.patch(f"/api/v1/files/nodes/{child['id']}", json={"parent_id": file["id"]})).status_code == 404

    owner_versions = await client.get(f"/api/v1/files/nodes/{file['id']}/versions")
    owner_download = await client.get(f"/api/v1/files/nodes/{file['id']}/download")
    assert owner_versions.status_code == 200 and owner_download.status_code == 200
    await _register_login(client, "files-other@example.com")
    assert (await client.get("/api/v1/files/nodes")).json() == []
    assert (await client.get(f"/api/v1/files/nodes?parent_id={root['id']}")).status_code == 404
    assert (await client.post("/api/v1/files/folders", json={"name": "x", "parent_id": root["id"]})).status_code == 404
    assert (
        await client.post(
            "/api/v1/files/upload", data={"parent_id": root["id"]}, files={"file": ("x.txt", b"x", "text/plain")}
        )
    ).status_code == 404
    assert (await client.patch(f"/api/v1/files/nodes/{file['id']}", json={"name": "x.md"})).status_code == 404
    assert (await client.delete(f"/api/v1/files/nodes/{root['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/files/nodes/{file['id']}/versions")).status_code == 404
    assert (await client.get(f"/api/v1/files/nodes/{file['id']}/download")).status_code == 404


async def test_failed_upload_leaves_no_blob_and_oversize_maps_413(
    client: httpx.AsyncClient, memory_storage: MemoryStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _register_login(client, "files-failure@example.com")
    monkeypatch.setattr(files_service, "MAX_UPLOAD_BYTES", 2)
    response = await client.post("/api/v1/files/upload", files={"file": ("large.txt", b"large", "text/plain")})
    assert response.status_code == 413
    assert memory_storage.objects == {}


async def test_database_failure_after_blob_write_cleans_blob(
    client: httpx.AsyncClient, memory_storage: MemoryStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    await _register_login(client, "files-db-failure@example.com")
    original_flush = AsyncSession.flush
    flushes = 0

    async def fail_after_version(self: AsyncSession, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        nonlocal flushes
        flushes += 1
        await original_flush(self, *args, **kwargs)
        if flushes == 2:
            raise RuntimeError("simulated database failure")

    monkeypatch.setattr(AsyncSession, "flush", fail_after_version)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        await client.post("/api/v1/files/upload", files={"file": ("written.txt", b"written", "text/plain")})
    assert memory_storage.objects == {}


async def test_failure_after_blob_write_cleans_blob(
    client: httpx.AsyncClient, memory_storage: MemoryStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    await _register_login(client, "files-commit-failure@example.com")
    original_flush = AsyncSession.flush

    async def fail_file_flush(self: AsyncSession, *args, **kwargs) -> None:
        if self.info.get("file_storage_cleanup"):
            raise RuntimeError("simulated database failure")
        await original_flush(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "flush", fail_file_flush)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        await client.post("/api/v1/files/upload", files={"file": ("commit.txt", b"written", "text/plain")})
    assert memory_storage.objects == {}


async def test_name_controls_and_long_names_are_rejected(client: httpx.AsyncClient) -> None:
    await _register_login(client, "files-names@example.com")
    sanitized = await client.post("/api/v1/files/folders", json={"name": "bad\u0001name"})
    assert sanitized.status_code == 201 and sanitized.json()["name"] == "badname"
    assert (await client.post("/api/v1/files/folders", json={"name": ".."})).status_code == 422
    assert (await client.post("/api/v1/files/folders", json={"name": "x" * 256})).status_code == 422
