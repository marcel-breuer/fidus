import base64
import io
import shutil
import subprocess
import wave
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.ai.fakes import FakeEmbeddingProvider, FakeSpeechProvider, FakeTranscriptionProvider
from app.ai.openai_provider import OpenAISpeechProvider, OpenAITranscriptionProvider
from app.db.models import Chunk, Document, Memo
from app.db.session import user_session
from app.services import audio as audio_service
from app.services.transcription import (
    TranscriptionError,
    process_memo,
    process_memo_job,
    split_with_ffmpeg,
    transcribe_segments,
)
from tests.helpers import PASSWORD, register

WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64


async def _login(client: httpx.AsyncClient, email: str) -> str:
    registered = await register(client, email)
    assert registered.status_code == 201
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    return registered.json()["id"]


async def _relogin(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""


async def _upload(client: httpx.AsyncClient, name: str = "note.webm", content: bytes = WEBM, **data: str) -> dict:
    response = await client.post(
        "/api/v1/audio/memos", files={"file": (name, content, "audio/webm")}, data=data
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _fake_segments(data: bytes, extension: str) -> list[bytes]:
    return [b"seg-one", b"seg-two"]


async def test_auth_csrf_and_module_guard(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/audio/memos")).status_code == 401
    await _login(client, "audio-guard@example.com")
    bad = await client.post(
        "/api/v1/audio/memos", files={"file": ("a.webm", WEBM, "audio/webm")}, headers={"X-CSRF-Token": "bad"}
    )
    assert bad.status_code == 403
    assert (await client.get("/api/v1/audio/memos")).json() == []
    # The first user is admin and may disable the module; its routes then disappear.
    assert (await client.put("/api/v1/admin/modules/audio", json={"enabled": False})).status_code == 200
    assert (await client.get("/api/v1/audio/memos")).status_code == 404
    assert "audio" not in [m["key"] for m in (await client.get("/api/v1/modules")).json()]
    assert (await client.put("/api/v1/admin/modules/audio", json={"enabled": True})).status_code == 200
    assert "audio" in [m["key"] for m in (await client.get("/api/v1/modules")).json()]


async def test_upload_validation(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, memory_storage) -> None:
    await _login(client, "audio-validate@example.com")

    async def post(name: str, content: bytes, **data: str) -> httpx.Response:
        return await client.post("/api/v1/audio/memos", files={"file": (name, content, "audio/webm")}, data=data)

    assert (await post("notes.txt", WEBM)).status_code == 415
    assert (await post("fake.webm", b"not audio at all")).status_code == 415
    assert (await post("empty.webm", b"")).status_code == 415
    assert (await post("a.webm", WEBM, language="de-DE!")).status_code == 422
    monkeypatch.setattr(audio_service, "MAX_MEMO_BYTES", 10)
    assert (await post("big.webm", WEBM)).status_code == 413
    assert memory_storage.objects == {}
    monkeypatch.undo()
    created = await _upload(client, "../../Weekly sync.webm", title="  Sync  ", language="de")
    assert created["title"] == "Sync" and created["status"] == "pending" and created["language"] == "de"
    default_title = await _upload(client, "Weekly sync.webm")
    assert default_title["title"] == "Weekly sync"


async def test_transcription_pipeline_creates_searchable_document(
    client: httpx.AsyncClient, memory_storage
) -> None:
    user_id = await _login(client, "audio-pipeline@example.com")
    memo = await _upload(client, language="en")
    transcriber = FakeTranscriptionProvider(["the quarterly budget review", "needs approval from finance"])
    await process_memo(user_id, memo["id"], memory_storage, transcriber, FakeEmbeddingProvider(), _fake_segments)

    assert [call[1] for call in transcriber.calls] == [b"seg-one", b"seg-two"]
    assert all(call[2] == "en" for call in transcriber.calls)
    detail = (await client.get(f"/api/v1/audio/memos/{memo['id']}")).json()
    assert detail["status"] == "ready" and detail["index_status"] == "ready"
    assert detail["transcript"] == "the quarterly budget review needs approval from finance"
    async with user_session(user_id) as session:
        document = await session.get(Document, detail["document_id"])
        chunks = list((await session.scalars(select(Chunk).where(Chunk.document_id == document.id))).all())
    assert document.source == "memo" and document.node_id is None and len(chunks) == 1

    found = (await client.get("/api/v1/knowledge/search", params={"q": "finance approval"})).json()["results"]
    assert found and found[0]["source"] == "memo" and found[0]["memo_id"] == memo["id"]
    assert found[0]["node_id"] is None and found[0]["version"] is None

    renamed = await client.patch(f"/api/v1/audio/memos/{memo['id']}", json={"title": "Budget call"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Budget call"
    found = (await client.get("/api/v1/knowledge/search", params={"q": "finance approval"})).json()["results"]
    assert found[0]["file_name"] == "Budget call"

    audio = await client.get(f"/api/v1/audio/memos/{memo['id']}/audio")
    assert audio.status_code == 200 and audio.content == WEBM and audio.headers["content-type"] == "audio/webm"

    # Disabling the audio module hides transcripts from knowledge search without touching data.
    assert (await client.put("/api/v1/admin/modules/audio", json={"enabled": False})).status_code == 200
    assert (await client.get("/api/v1/knowledge/search", params={"q": "finance approval"})).json()["results"] == []
    assert (await client.put("/api/v1/admin/modules/audio", json={"enabled": True})).status_code == 200
    assert (await client.get("/api/v1/knowledge/search", params={"q": "finance approval"})).json()["results"]


async def test_failed_transcription_stores_stable_code_and_retry_succeeds(
    client: httpx.AsyncClient, memory_storage
) -> None:
    user_id = await _login(client, "audio-retry@example.com")
    memo = await _upload(client)
    assert (await client.post(f"/api/v1/audio/memos/{memo['id']}/retry")).status_code == 409
    failing = FakeTranscriptionProvider([RuntimeError("secret provider detail sk-123")])
    await process_memo(user_id, memo["id"], memory_storage, failing, FakeEmbeddingProvider(), _fake_segments)
    failed = (await client.get(f"/api/v1/audio/memos/{memo['id']}")).json()
    assert failed["status"] == "failed" and failed["error_code"] == "TRANSCRIPTION_FAILED"
    assert "secret" not in str(failed) and failed["transcript"] is None

    retried = await client.post(f"/api/v1/audio/memos/{memo['id']}/retry")
    assert retried.status_code == 200 and retried.json()["status"] == "pending"
    await process_memo(
        user_id, memo["id"], memory_storage, FakeTranscriptionProvider(["recovered text"]),
        FakeEmbeddingProvider(), _fake_segments,
    )
    transcript = (await client.get(f"/api/v1/audio/memos/{memo['id']}")).json()["transcript"]
    assert transcript == "recovered text recovered text"


async def test_missing_provider_and_empty_transcript_and_embedding_failure(
    client: httpx.AsyncClient, memory_storage
) -> None:
    user_id = await _login(client, "audio-codes@example.com")
    first = await _upload(client)
    await process_memo(user_id, first["id"], memory_storage, None, None, _fake_segments)
    assert (await client.get(f"/api/v1/audio/memos/{first['id']}")).json()["error_code"] == "AI_NOT_CONFIGURED"

    second = await _upload(client)
    await process_memo(
        user_id, second["id"], memory_storage, FakeTranscriptionProvider(["  ", ""]),
        FakeEmbeddingProvider(), _fake_segments,
    )
    assert (await client.get(f"/api/v1/audio/memos/{second['id']}")).json()["error_code"] == "EMPTY_TRANSCRIPT"

    class BrokenEmbedder:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("boom")

    third = await _upload(client)
    await process_memo(
        user_id, third["id"], memory_storage, FakeTranscriptionProvider(["kept words"]), BrokenEmbedder(),
        _fake_segments,
    )
    detail = (await client.get(f"/api/v1/audio/memos/{third['id']}")).json()
    # The transcript survives an indexing failure and the memo can retry indexing only.
    assert detail["status"] == "ready" and detail["transcript"] == "kept words kept words"
    assert detail["index_status"] == "failed" and detail["index_error_code"] == "INDEXING_FAILED"
    assert (await client.post(f"/api/v1/audio/memos/{third['id']}/retry")).json()["index_status"] == "pending"
    transcriber = FakeTranscriptionProvider(["must not be called"])
    await process_memo(user_id, third["id"], memory_storage, transcriber, FakeEmbeddingProvider(), _fake_segments)
    assert transcriber.calls == []
    assert (await client.get(f"/api/v1/audio/memos/{third['id']}")).json()["index_status"] == "ready"


async def test_worker_job_skips_disabled_module(client: httpx.AsyncClient, memory_storage) -> None:
    user_id = await _login(client, "audio-disabled@example.com")
    memo = await _upload(client)
    assert (await client.put("/api/v1/admin/modules/audio", json={"enabled": False})).status_code == 200
    transcriber = FakeTranscriptionProvider(["x"])
    await process_memo_job(
        user_id, memo["id"], memory_storage, transcriber, FakeEmbeddingProvider(), _fake_segments
    )
    assert transcriber.calls == []
    assert (await client.put("/api/v1/admin/modules/audio", json={"enabled": True})).status_code == 200
    assert (await client.get(f"/api/v1/audio/memos/{memo['id']}")).json()["status"] == "pending"
    await process_memo_job(
        user_id, memo["id"], memory_storage, transcriber, FakeEmbeddingProvider(), _fake_segments
    )
    assert (await client.get(f"/api/v1/audio/memos/{memo['id']}")).json()["status"] == "ready"


async def test_speech_is_generated_once_and_cached(
    client: httpx.AsyncClient, memory_storage, speech_provider: FakeSpeechProvider
) -> None:
    user_id = await _login(client, "audio-speech@example.com")
    memo = await _upload(client)
    assert (await client.post(f"/api/v1/audio/memos/{memo['id']}/speech")).json()["detail"] == "NO_TRANSCRIPT"
    long_text = " ".join([f"Sentence number {number} is here." for number in range(250)])
    await process_memo(
        user_id, memo["id"], memory_storage, FakeTranscriptionProvider([long_text]),
        FakeEmbeddingProvider(), lambda data, ext: _single(data),
    )
    first = await client.post(f"/api/v1/audio/memos/{memo['id']}/speech")
    assert first.status_code == 200 and first.headers["content-type"] == "audio/wav"
    assert len(speech_provider.texts) >= 2 and all(len(text) <= 3500 for text in speech_provider.texts)
    with wave.open(io.BytesIO(first.content)) as wav:
        assert wav.getframerate() == 24000 and wav.getnframes() == sum(len(t) for t in speech_provider.texts)
    calls = len(speech_provider.texts)
    second = await client.post(f"/api/v1/audio/memos/{memo['id']}/speech")
    assert second.content == first.content and len(speech_provider.texts) == calls

    async with user_session(user_id) as session:
        row = await session.get(Memo, memo["id"])
        document = await session.get(Document, row.document_id)
        document.content = "x" * (audio_service.MAX_SPEECH_CHARS + 1)
        row.speech_key = None
    assert (await client.post(f"/api/v1/audio/memos/{memo['id']}/speech")).json()["detail"] == "TEXT_TOO_LONG"


async def _single(data: bytes) -> list[bytes]:
    return [data]


async def test_speech_provider_failure_is_a_stable_error(
    client: httpx.AsyncClient, memory_storage, speech_provider
) -> None:
    user_id = await _login(client, "audio-speech-fail@example.com")
    memo = await _upload(client)
    await process_memo(
        user_id, memo["id"], memory_storage, FakeTranscriptionProvider(["hello"]),
        FakeEmbeddingProvider(), _fake_segments,
    )

    async def broken(text: str) -> bytes:
        raise RuntimeError("private upstream detail")

    speech_provider.synthesize = broken  # type: ignore[method-assign]
    response = await client.post(f"/api/v1/audio/memos/{memo['id']}/speech")
    assert response.status_code == 502 and response.json()["detail"] == "SPEECH_FAILED"


async def test_delete_removes_blobs_document_and_chunks(client: httpx.AsyncClient, memory_storage) -> None:
    user_id = await _login(client, "audio-delete@example.com")
    memo = await _upload(client)
    await process_memo(
        user_id, memo["id"], memory_storage, FakeTranscriptionProvider(["gone soon"]),
        FakeEmbeddingProvider(), _fake_segments,
    )
    await client.post(f"/api/v1/audio/memos/{memo['id']}/speech")
    assert len(memory_storage.objects) == 2
    assert (await client.delete(f"/api/v1/audio/memos/{memo['id']}")).status_code == 204
    assert memory_storage.objects == {}
    async with user_session(user_id) as session:
        assert await session.scalar(select(Document.id)) is None
        assert await session.scalar(select(Chunk.id)) is None
        assert await session.scalar(select(Memo.id)) is None
    assert (await client.delete(f"/api/v1/audio/memos/{memo['id']}")).status_code == 404


async def test_user_b_cannot_reach_user_a_memos(client: httpx.AsyncClient, memory_storage, speech_provider) -> None:
    a_email, b_email = "audio-a@example.com", "audio-b@example.com"
    a_id = await _login(client, a_email)
    memo = await _upload(client, title="Private")
    await process_memo(
        a_id, memo["id"], memory_storage, FakeTranscriptionProvider(["confidential merger plans"]),
        FakeEmbeddingProvider(), _fake_segments,
    )
    b_id = await _login(client, b_email)
    base = f"/api/v1/audio/memos/{memo['id']}"
    assert (await client.get("/api/v1/audio/memos")).json() == []
    assert (await client.get(base)).status_code == 404
    assert (await client.get(f"{base}/audio")).status_code == 404
    assert (await client.patch(base, json={"title": "x"})).status_code == 404
    assert (await client.post(f"{base}/retry")).status_code == 404
    assert (await client.post(f"{base}/speech")).status_code == 404
    assert speech_provider.texts == []
    assert (await client.delete(base)).status_code == 404
    assert (await client.get("/api/v1/knowledge/search", params={"q": "confidential merger"})).json()["results"] == []
    async with user_session(b_id) as session:
        assert await session.scalar(select(Memo.id)) is None
        assert await session.scalar(select(Document.id)) is None
    # B's own processing job cannot act on A's memo either.
    transcriber = FakeTranscriptionProvider(["intruder"])
    await process_memo(b_id, memo["id"], memory_storage, transcriber, FakeEmbeddingProvider(), _fake_segments)
    assert transcriber.calls == []
    await _relogin(client, a_email)
    assert (await client.get(base)).json()["transcript"] == "confidential merger plans confidential merger plans"
    assert len(memory_storage.objects) == 1


async def test_transcribe_segments_joins_in_order_and_reports_codes() -> None:
    transcriber = FakeTranscriptionProvider(["alpha", "beta"])
    assert await transcribe_segments(b"x", ".webm", transcriber, _fake_segments) == "alpha beta"
    with pytest.raises(TranscriptionError) as error:
        await transcribe_segments(b"x", ".webm", FakeTranscriptionProvider([RuntimeError("x")]), _fake_segments)
    assert error.value.code == "TRANSCRIPTION_FAILED"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_ffmpeg_splits_long_audio_into_small_segments(tmp_path) -> None:
    source = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=25", str(source)], check=True
    )
    segments = await split_with_ffmpeg(source.read_bytes(), ".wav", segment_seconds=10)
    assert len(segments) == 3
    assert all(0 < len(segment) < 25 * 1024 * 1024 for segment in segments)
    assert all(segment[:3] == b"ID3" or segment[0] == 0xFF for segment in segments)
    with pytest.raises(TranscriptionError) as error:
        await split_with_ffmpeg(b"definitely not audio", ".wav")
    assert error.value.code == "CORRUPT_AUDIO"


async def test_openai_transcription_provider_uses_configured_model() -> None:
    calls: list[dict[str, object]] = []

    class Transcriptions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return " hello world \n"

    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=Transcriptions()))
    text = await OpenAITranscriptionProvider(client).transcribe(b"bytes", "a.mp3", "de")
    assert text == "hello world"
    assert calls[0]["model"] == "gpt-transcribe" and calls[0]["language"] == "de"
    assert calls[0]["file"] == ("a.mp3", b"bytes")


async def test_openai_speech_provider_collects_pcm_into_wav() -> None:
    sent: list[tuple[str, object]] = []

    class Connection:
        def __init__(self) -> None:
            self.session = SimpleNamespace(update=self._record("session"))
            self.conversation = SimpleNamespace(item=SimpleNamespace(create=self._record("item")))
            self.response = SimpleNamespace(create=self._record("response"))

        def _record(self, name: str):
            async def call(**kwargs) -> None:
                sent.append((name, kwargs))

            return call

        async def __aenter__(self) -> "Connection":
            return self

        async def __aexit__(self, *args) -> None:
            return None

        def __aiter__(self):
            async def events():
                yield SimpleNamespace(type="response.created")
                for pcm in (b"\x01\x00\x02\x00", b"\x03\x00"):
                    yield SimpleNamespace(type="response.output_audio.delta", delta=base64.b64encode(pcm).decode())
                yield SimpleNamespace(type="response.done")
                yield SimpleNamespace(type="response.output_audio.delta", delta=base64.b64encode(b"zz").decode())

            return events()

    models: list[str] = []

    def connect(model: str) -> Connection:
        models.append(model)
        return Connection()

    wav_bytes = await OpenAISpeechProvider(SimpleNamespace(realtime=SimpleNamespace(connect=connect))).synthesize("Hi")
    assert models == ["gpt-realtime-2.1-mini"]
    with wave.open(io.BytesIO(wav_bytes)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (24000, 1, 2)
        assert wav.readframes(10) == b"\x01\x00\x02\x00\x03\x00"
    names = [name for name, _ in sent]
    assert names == ["session", "item", "response"]
    assert sent[0][1]["session"]["output_modalities"] == ["audio"]
    assert sent[1][1]["item"]["content"][0]["text"] == "Hi"


async def test_stale_transcriptions_are_requeued_once_and_only_for_owner(
    client: httpx.AsyncClient, memory_storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker.tasks import recover_stuck_memos

    alice_id = await _login(client, "stale-alice@example.com")
    alice_memo = await _upload(client)
    await _login(client, "stale-bob@example.com")
    bob_id = await client.get("/api/v1/users/me")
    bob_memo = await _upload(client, "fresh.webm")
    assert bob_id.status_code == 200

    old = datetime.now(UTC) - timedelta(hours=1)
    async with user_session(alice_id) as session:
        memo = await session.get(Memo, alice_memo["id"])
        assert memo is not None
        memo.status = "transcribing"
        memo.updated_at = old
    async with user_session(bob_id.json()["id"]) as session:
        memo = await session.get(Memo, bob_memo["id"])
        assert memo is not None
        memo.status = "transcribing"

    queued: list[tuple[str, str]] = []

    async def record_enqueue(user_id: str, memo_id: str) -> None:
        queued.append((user_id, memo_id))

    monkeypatch.setattr("app.worker.tasks.enqueue_memo", record_enqueue)
    now = datetime.now(UTC)
    assert await recover_stuck_memos(now, 600) == 1
    assert queued == [(alice_id, alice_memo["id"])]
    async with user_session(alice_id) as session:
        recovered = await session.get(Memo, alice_memo["id"])
        assert recovered is not None and recovered.status == "pending"
        recovered.updated_at = old
    assert await recover_stuck_memos(now, 600) == 1
    assert queued == [(alice_id, alice_memo["id"]), (alice_id, alice_memo["id"])]
    assert await recover_stuck_memos(now, 600) == 0
    async with user_session(alice_id) as session:
        recovered = await session.get(Memo, alice_memo["id"])
        assert recovered is not None and recovered.status == "pending"
    async with user_session(bob_id.json()["id"]) as session:
        untouched = await session.get(Memo, bob_memo["id"])
        assert untouched is not None and untouched.status == "transcribing"


async def test_duplicate_transcription_job_does_not_transcribe_again(
    client: httpx.AsyncClient, memory_storage
) -> None:
    user_id = await _login(client, "duplicate-job@example.com")
    memo = await _upload(client)
    async with user_session(user_id) as session:
        row = await session.get(Memo, memo["id"])
        assert row is not None
        row.status = "transcribing"
    transcriber = FakeTranscriptionProvider(["must not run"])
    await process_memo(user_id, memo["id"], memory_storage, transcriber, FakeEmbeddingProvider(), _fake_segments)
    assert transcriber.calls == []
    assert (await client.get(f"/api/v1/audio/memos/{memo['id']}")).json()["status"] == "transcribing"
