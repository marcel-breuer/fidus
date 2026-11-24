import httpx
import pytest
from sqlalchemy import select

from app.ai.fakes import FakeTranscriptionProvider
from app.db.models import Memo, UsageRecord, User
from app.db.session import user_session
from app.services import chat_audio
from app.services.conversations import add_message
from app.services.transcription import ShortTranscription, TranscriptionError, transcribe_short_clip
from tests.helpers import PASSWORD, register

WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64


async def _login(client: httpx.AsyncClient, email: str) -> str:
    created = await register(client, email)
    assert created.status_code == 201
    response = await client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD})
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    return created.json()["id"]


async def test_message_speech_is_cached_and_private(client, memory_storage, speech_provider) -> None:  # type: ignore[no-untyped-def]
    user_id = await _login(client, "chat-speech-owner@example.com")
    conversation = (await client.post("/api/v1/conversations", json={})).json()
    async with user_session(user_id) as session:
        user = await session.get(User, user_id)
        assert user is not None
        message = await add_message(session, user, conversation["id"], "assistant", "Hello from chat.")
        assert message is not None
        message_id = message.id

    url = f"/api/v1/conversations/{conversation['id']}/messages/{message_id}/speech"
    assert (await client.put("/api/v1/admin/modules/audio", json={"enabled": False})).status_code == 200
    first = await client.post(url)
    assert first.status_code == 200 and first.headers["content-type"] == "audio/wav"
    calls = len(speech_provider.texts)
    second = await client.post(url)
    assert second.content == first.content and len(speech_provider.texts) == calls
    assert len(memory_storage.objects) == 1
    assert (await client.put("/api/v1/admin/modules/audio", json={"enabled": True})).status_code == 200

    await register(client, "chat-speech-other@example.com")
    response = await client.post("/api/v1/auth/login", data={
        "username": "chat-speech-other@example.com", "password": PASSWORD
    })
    assert response.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    denied = await client.post(url)
    assert denied.status_code == 404 and len(speech_provider.texts) == calls
    owner_login = await client.post("/api/v1/auth/login", data={
        "username": "chat-speech-owner@example.com", "password": PASSWORD
    })
    assert owner_login.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    assert (await client.delete(f"/api/v1/conversations/{conversation['id']}")).status_code == 204
    assert memory_storage.objects == {}


async def test_dictation_is_synchronous_bounded_and_does_not_create_memo(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, settings
) -> None:  # type: ignore[no-untyped-def]
    owner_id = await _login(client, "dictation-owner@example.com")
    conversation = (await client.post("/api/v1/conversations", json={})).json()
    settings.transcription_rate_limit_requests = 1
    calls = 0

    async def fake_transcribe(data, filename, provider, max_seconds, language=None):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        assert max_seconds == 60
        assert data == WEBM and filename == "dictation.webm" and language == "de"
        return ShortTranscription("recognized words", 8)

    monkeypatch.setattr(chat_audio, "transcribe_short_clip", fake_transcribe)
    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/dictation",
        files={"file": ("dictation.webm", WEBM, "audio/webm")},
        params={"language": "de"},
    )
    assert response.status_code == 200 and response.json() == {"text": "recognized words"}
    limited = await client.post(
        f"/api/v1/conversations/{conversation['id']}/dictation",
        files={"file": ("dictation.webm", WEBM, "audio/webm")},
    )
    assert limited.status_code == 429 and calls == 1
    async with user_session(owner_id) as session:
        assert await session.scalar(select(Memo.id).where(Memo.user_id == owner_id)) is None
        usage_row = await session.scalar(
            select(UsageRecord).where(UsageRecord.user_id == owner_id, UsageRecord.metric == "transcription_seconds")
        )
        assert usage_row is not None and usage_row.quantity == 8

    await register(client, "dictation-other@example.com")
    login = await client.post("/api/v1/auth/login", data={
        "username": "dictation-other@example.com", "password": PASSWORD
    })
    assert login.status_code == 204
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    denied = await client.post(
        f"/api/v1/conversations/{conversation['id']}/dictation",
        files={"file": ("dictation.webm", WEBM, "audio/webm")},
    )
    assert denied.status_code == 404


async def test_dictation_rejects_unsupported_oversize_and_invalid_language() -> None:
    provider = FakeTranscriptionProvider(["not called"])
    with pytest.raises(chat_audio.ChatAudioError, match="UNSUPPORTED_TYPE"):
        await chat_audio.transcribe_dictation("user", b"bad", "voice.txt", provider)
    with pytest.raises(chat_audio.ChatAudioError, match="FILE_TOO_LARGE"):
        await chat_audio.transcribe_dictation(
            "user", b"x" * (chat_audio.MAX_DICTATION_BYTES + 1), "voice.webm", provider
        )
    with pytest.raises(chat_audio.ChatAudioError, match="INVALID_LANGUAGE"):
        await chat_audio.transcribe_dictation("user", WEBM, "voice.webm", provider, "de-DE!")
    assert provider.calls == []

    async def overlong_segment(data: bytes, extension: str) -> list[bytes]:
        return [b"x" * 244_001]

    with pytest.raises(TranscriptionError, match="CLIP_TOO_LONG"):
        await transcribe_short_clip(WEBM, "voice.webm", provider, 60, segmenter=overlong_segment)
    assert provider.calls == []
