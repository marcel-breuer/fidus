"""Opaque keyset cursors shared by administrative list operations."""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Cursor:
    created_at: datetime
    item_id: str


class InvalidCursor(ValueError):
    """A client supplied cursor is malformed."""


def encode_cursor(created_at: datetime, item_id: str) -> str:
    raw = json.dumps([created_at.isoformat(), item_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str | None) -> Cursor | None:
    if value is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        created_at, item_id = json.loads(raw)
        if not isinstance(created_at, str) or not isinstance(item_id, str) or len(item_id) != 26:
            raise ValueError
        timestamp = datetime.fromisoformat(created_at)
        if timestamp.utcoffset() is None:
            raise ValueError
        return Cursor(timestamp, item_id)
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError) as exc:
        raise InvalidCursor from exc
