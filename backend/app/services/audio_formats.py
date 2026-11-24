"""Supported audio formats and lightweight container signature checks."""

TYPES = {
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".mpga": "audio/mpeg",
    ".mpeg": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
}
EXTENSIONS = {mime: ext for ext, mime in reversed(list(TYPES.items()))}


def extension_for_mime(mime_type: str) -> str:
    return EXTENSIONS.get(mime_type, ".bin")


def matches_signature(extension: str, head: bytes) -> bool:
    if extension == ".webm":
        return head.startswith(b"\x1a\x45\xdf\xa3")
    if extension in {".ogg", ".oga"}:
        return head.startswith(b"OggS")
    if extension in {".mp3", ".mpga", ".mpeg"}:
        return head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
    if extension in {".m4a", ".mp4"}:
        return head[4:8] == b"ftyp"
    if extension == ".wav":
        return head.startswith(b"RIFF") and head[8:12] == b"WAVE"
    if extension == ".flac":
        return head.startswith(b"fLaC")
    return False
