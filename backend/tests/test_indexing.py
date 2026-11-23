import httpx
import pytest
from sqlalchemy import select

from app.ai.fakes import FakeEmbeddingProvider
from app.db.models import Chunk, Document, FileVersion
from app.db.session import user_session
from app.worker.tasks import process_index_document
from tests.helpers import PASSWORD, register


async def _login(client: httpx.AsyncClient, email: str) -> str:
	registered = await register(client, email)
	assert registered.status_code == 201
	response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
	assert response.status_code == 204
	client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
	return registered.json()["id"]


async def _upload(client: httpx.AsyncClient, name: str, content: bytes) -> str:
	response = await client.post("/api/v1/files/upload", files={"file": (name, content, "text/plain")})
	assert response.status_code == 201
	return response.json()["id"]


async def test_indexing_stores_chunks_and_new_version_removes_stale_chunks(
	client: httpx.AsyncClient, memory_storage, monkeypatch: pytest.MonkeyPatch
) -> None:
	async def ignore_queue(user_id: str, document_id: str) -> None:
		return None

	monkeypatch.setattr("app.services.indexing.enqueue_index_document", ignore_queue)
	user_id = await _login(client, "indexing-happy@example.com")
	node_id = await _upload(client, "notes.txt", b"shared words in the first version")
	async with user_session(user_id) as session:
		document_id = await session.scalar(select(Document.id).where(Document.node_id == node_id))
	assert document_id is not None
	await process_index_document(user_id, document_id, memory_storage, FakeEmbeddingProvider())
	async with user_session(user_id) as session:
		document = await session.get(Document, document_id)
		chunks = list((await session.scalars(select(Chunk).where(Chunk.document_id == document_id))).all())
	assert document is not None and document.status == "ready" and document.chunk_count == 1
	assert len(chunks) == 1 and len(chunks[0].embedding) == 1536
	search = await client.get("/api/v1/knowledge/search", params={"q": "shared words"})
	assert search.status_code == 200
	assert search.json()["results"][0]["file_name"] == "notes.txt"

	await _upload(client, "notes.txt", b"shared words in the second version")
	async with user_session(user_id) as session:
		latest_id = await session.scalar(
			select(Document.id)
			.join(FileVersion, Document.version_id == FileVersion.id)
			.where(Document.node_id == node_id)
			.order_by(FileVersion.version.desc())
			.limit(1)
		)
	assert latest_id is not None
	await process_index_document(user_id, latest_id, memory_storage, FakeEmbeddingProvider())
	async with user_session(user_id) as session:
		assert await session.scalar(select(Chunk.id).where(Chunk.document_id == document_id)) is None
		assert await session.scalar(select(Chunk.id).where(Chunk.document_id == latest_id)) is not None

	deleted = await client.delete(f"/api/v1/files/nodes/{node_id}")
	assert deleted.status_code == 204
	async with user_session(user_id) as session:
		assert await session.scalar(select(Document.id).where(Document.node_id == node_id)) is None
		assert await session.scalar(select(Chunk.id).where(Chunk.document_id == latest_id)) is None


async def test_worker_indexing_reports_extraction_failure(
	client: httpx.AsyncClient, memory_storage, monkeypatch: pytest.MonkeyPatch
) -> None:
	async def ignore_queue(user_id: str, document_id: str) -> None:
		return None

	monkeypatch.setattr("app.services.indexing.enqueue_index_document", ignore_queue)
	user_id = await _login(client, "indexing-failure@example.com")
	node_id = await _upload(client, "bad.pdf", b"%PDF- invalid document bytes")
	async with user_session(user_id) as session:
		document_id = await session.scalar(select(Document.id).where(Document.node_id == node_id))
	assert document_id is not None
	await process_index_document(user_id, document_id, memory_storage, FakeEmbeddingProvider())
	async with user_session(user_id) as session:
		document = await session.get(Document, document_id)
	assert document is not None and document.status == "failed"
	assert document.error_code == "CORRUPT_FILE"


async def test_worker_marks_document_ai_not_configured(
	client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
	from fastapi import HTTPException
	from sqlalchemy import select

	from app.db.models import Document
	from app.db.session import user_session

	async def ignore_queue(user_id: str, document_id: str) -> None:
		return None

	monkeypatch.setattr("app.services.indexing.enqueue_index_document", ignore_queue)
	user_id = await _login(client, "indexing-no-key@example.com")
	node_id = await _upload(client, "waiting.txt", b"awaiting index")
	async with user_session(user_id) as session:
		document_id = await session.scalar(select(Document.id).where(Document.node_id == node_id))
	assert document_id is not None

	def no_key():
		raise HTTPException(status_code=503, detail="AI_NOT_CONFIGURED")

	monkeypatch.setattr("app.worker.tasks.get_embedding_provider", no_key)
	from app.worker.tasks import index_document_job

	await index_document_job(user_id, document_id)
	status = await client.get(f"/api/v1/files/nodes/{node_id}/document")
	assert status.json()["status"] == "failed"
	assert status.json()["error_code"] == "AI_NOT_CONFIGURED"


async def test_search_does_not_return_another_users_chunks(
	client: httpx.AsyncClient, memory_storage, monkeypatch: pytest.MonkeyPatch
) -> None:
	async def ignore_queue(user_id: str, document_id: str) -> None:
		return None

	monkeypatch.setattr("app.services.indexing.enqueue_index_document", ignore_queue)
	owner_id = await _login(client, "knowledge-owner@example.com")
	node_id = await _upload(client, "private.txt", b"confidential emerald terms")
	async with user_session(owner_id) as session:
		document_id = await session.scalar(select(Document.id).where(Document.node_id == node_id))
	assert document_id is not None
	await process_index_document(owner_id, document_id, memory_storage, FakeEmbeddingProvider())

	await client.post("/api/v1/auth/logout")
	client.headers.pop("X-CSRF-Token", None)
	await _login(client, "knowledge-other@example.com")
	response = await client.get("/api/v1/knowledge/search", params={"q": "confidential emerald"})
	assert response.status_code == 200
	assert response.json()["results"] == []


async def test_search_rejects_empty_query_and_invalid_limit(client: httpx.AsyncClient) -> None:
	assert (await client.get("/api/v1/knowledge/search", params={"q": "x"})).status_code == 401
	await _login(client, "knowledge-validation@example.com")
	assert (await client.get("/api/v1/knowledge/search", params={"q": "   "})).status_code == 422
	assert (await client.get("/api/v1/knowledge/search", params={"q": "words", "limit": 21})).status_code == 422
