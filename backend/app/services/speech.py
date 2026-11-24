"""Shared speech audio helpers for memo transcripts and chat messages."""

import io
import wave

MAX_SPEECH_CHARS = 12000
SPEECH_CHUNK_CHARS = 3500


def join_wav(parts: list[bytes]) -> bytes:
    if len(parts) == 1:
        return parts[0]
    frames = bytearray()
    params = None
    for part in parts:
        with wave.open(io.BytesIO(part)) as source:
            params = params or source.getparams()
            frames.extend(source.readframes(source.getnframes()))
    assert params is not None
    out = io.BytesIO()
    with wave.open(out, "wb") as target:
        target.setparams(params)
        target.writeframes(bytes(frames))
    return out.getvalue()
