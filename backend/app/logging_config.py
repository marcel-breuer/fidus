"""Structured JSON logging for the backend and the worker.

Privacy rule: a log line never carries user content. Records are rendered from an allow-list of
structured fields (ids, counts, durations, status codes); anything passed through `extra` that is
not on the list is dropped, exception messages are replaced by the exception type plus stack
locations, and secret-shaped substrings in the message are scrubbed as a last line of defense.
"""

import contextvars
import json
import logging
import re
import sys
import traceback
from datetime import UTC, datetime

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

# Keys that may appear in `extra=`. Every one is an identifier, a number or a short enum.
ALLOWED_FIELDS = frozenset({
    "user_id", "memo_id", "document_id", "task_id", "token_id", "conversation_id",
    "method", "route", "status", "duration_ms", "event", "reason", "attempt",
})

REDACTED = "[redacted]"
_SECRET_PATTERNS = (
    re.compile(r"fidus_pat_[A-Za-z0-9_\-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"(?i)\b(fidus_session|fidus_csrf|authorization|cookie|set-cookie|password|api[_-]?key|secret)"
               r"(\s*[=:]\s*)[^\s,;]+"),
)
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")


def scrub(text: str) -> str:
    for pattern in _SECRET_PATTERNS[:3]:
        text = pattern.sub(REDACTED, text)
    return _SECRET_PATTERNS[3].sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)


def valid_request_id(value: str | None) -> str | None:
    return value if value is not None and _REQUEST_ID.fullmatch(value) else None


def _stack(exc: BaseException) -> list[str]:
    """Function locations only: no source lines (they may hold values) and no exception message."""
    tb = exc.__traceback__
    return [f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno}:{f.name}" for f in traceback.extract_tb(tb)][-12:]


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": scrub(record.getMessage()),
        }
        request_id = request_id_var.get()
        if request_id:
            entry["request_id"] = request_id
        for key in ALLOWED_FIELDS:
            value = record.__dict__.get(key)
            if isinstance(value, str):
                entry[key] = scrub(value)[:200]
            elif isinstance(value, int | float) and not isinstance(value, bool):
                entry[key] = value
        if record.exc_info and record.exc_info[1] is not None:
            entry["exc_type"] = type(record.exc_info[1]).__name__
            entry["stack"] = _stack(record.exc_info[1])
        return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


def configure_logging(service: str, level: int = logging.INFO) -> None:
    """Route every logger, including uvicorn's and taskiq's, through one JSON stream handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "taskiq", "taskiq.worker", "taskiq.receiver"):
        library = logging.getLogger(name)
        library.handlers.clear()
        library.propagate = True
    # The request middleware writes one structured access line; uvicorn's own would repeat it.
    logging.getLogger("uvicorn.access").disabled = True
    # httpx logs full request URLs at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
