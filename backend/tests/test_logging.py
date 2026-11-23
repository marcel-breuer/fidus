import io
import json
import logging
import re
from collections.abc import Iterator

import httpx
import pytest

from app.ai.fakes import FakeChatProvider
from app.logging_config import JsonFormatter, request_id_var, scrub, valid_request_id
from tests.helpers import PASSWORD, register

API_KEY = "sk-proj-abcdef1234567890SECRETKEY"
TOKEN = "fidus_pat_AbCdEf123456_SECRET"


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    """Capture what the production formatter would print for every logger."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter("test"))
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    yield stream
    root.removeHandler(handler)
    root.setLevel(previous_level)


def _lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def _record(message: str = "hello", **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("t", logging.WARNING, __file__, 1, message, None, None)
    record.__dict__.update(extra)
    return record


def test_output_is_one_json_object_with_core_fields() -> None:
    line = JsonFormatter("backend").format(_record("hello", user_id="01HABC", status=200, duration_ms=1.5))
    data = json.loads(line)
    assert "\n" not in line
    assert data["service"] == "backend" and data["level"] == "WARNING" and data["message"] == "hello"
    assert data["user_id"] == "01HABC" and data["status"] == 200 and data["duration_ms"] == 1.5
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:.]+\+00:00", data["ts"])


def test_request_id_comes_from_the_context() -> None:
    token = request_id_var.set("abcdef123456")
    try:
        assert json.loads(JsonFormatter("x").format(_record()))["request_id"] == "abcdef123456"
    finally:
        request_id_var.reset(token)
    assert "request_id" not in json.loads(JsonFormatter("x").format(_record()))


def test_fields_outside_the_allow_list_are_dropped() -> None:
    line = JsonFormatter("x").format(_record(
        content="my private message", filename="tax-2025.pdf", transcript="secret words",
        cookie="fidus_session=abc", authorization=f"Bearer {TOKEN}", api_key=API_KEY, memo_id="01HMEMO",
    ))
    for forbidden in ("my private message", "tax-2025.pdf", "secret words", "fidus_session", TOKEN, API_KEY):
        assert forbidden not in line
    assert json.loads(line)["memo_id"] == "01HMEMO"


def test_secret_shaped_values_are_scrubbed_from_messages_and_allowed_fields() -> None:
    record = _record(f"call failed with key {API_KEY} and Bearer abcdefgh12345678 and {TOKEN}", reason=API_KEY)
    line = JsonFormatter("x").format(record)
    for secret in (API_KEY, TOKEN, "abcdefgh12345678"):
        assert secret not in line
    assert "[redacted]" in line
    assert "password=[redacted]" in scrub("password=hunter2 and fidus_session=abcdef")
    assert "hunter2" not in scrub("password=hunter2")


def test_exceptions_log_type_and_locations_but_never_the_message() -> None:
    try:
        raise ValueError("user said: my diagnosis is private")
    except ValueError:
        import sys

        record = _record("failed")
        record.exc_info = sys.exc_info()
    data = json.loads(JsonFormatter("x").format(record))
    assert data["exc_type"] == "ValueError"
    assert any("test_logging.py" in frame for frame in data["stack"])
    assert "diagnosis" not in json.dumps(data)


def test_request_id_validation() -> None:
    assert valid_request_id("abc12345-DEF_6") == "abc12345-DEF_6"
    for bad in (None, "", "short", "has space in it", "x" * 65, "line\nbreak12345"):
        assert valid_request_id(bad) is None


async def test_response_carries_a_request_id_and_inbound_ids_are_validated(client: httpx.AsyncClient) -> None:
    generated = (await client.get("/health")).headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    echoed = await client.get("/health", headers={"X-Request-ID": "trace-1234567890"})
    assert echoed.headers["x-request-id"] == "trace-1234567890"
    replaced = await client.get("/health", headers={"X-Request-ID": "bad id\twith junk"})
    assert re.fullmatch(r"[0-9a-f]{32}", replaced.headers["x-request-id"])


async def test_access_log_has_route_template_and_no_query_or_credentials(
    client: httpx.AsyncClient, log_stream: io.StringIO
) -> None:
    await register(client, "log-user@example.com")
    response = await client.post("/api/v1/auth/login", data={"username": "log-user@example.com", "password": PASSWORD})
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    session_cookie = client.cookies.get("fidus_session") or ""
    assert session_cookie
    response = await client.get(
        "/api/v1/search/messages", params={"q": "my secret search words"},
        headers={"X-Request-ID": "trace-abcdef1234"},
    )
    assert response.status_code in (200, 422)

    output = log_stream.getvalue()
    for forbidden in ("my secret search words", "log-user@example.com", PASSWORD, session_cookie):
        assert forbidden not in output
    access = [entry for entry in _lines(log_stream) if entry["logger"] == "fidus.access"]
    assert access, output
    assert all({"method", "route", "status", "duration_ms", "request_id"} <= entry.keys() for entry in access)
    search = [entry for entry in access if entry["request_id"] == "trace-abcdef1234"]
    assert len(search) == 1 and search[0]["method"] == "GET"
    assert "search" in search[0]["route"] and "?" not in search[0]["route"]


async def test_health_checks_are_not_logged(client: httpx.AsyncClient, log_stream: io.StringIO) -> None:
    await client.get("/health")
    await client.get("/api/v1/health")
    assert not [entry for entry in _lines(log_stream) if entry["logger"] == "fidus.access"]


async def test_failed_chat_turn_logs_no_prompt_answer_or_provider_message(
    client: httpx.AsyncClient, chat_provider: FakeChatProvider, log_stream: io.StringIO
) -> None:
    await register(client, "log-chat@example.com")
    await client.post("/api/v1/auth/login", data={"username": "log-chat@example.com", "password": PASSWORD})
    client.headers["X-CSRF-Token"] = client.cookies.get("fidus_csrf") or ""
    conversation = (await client.post("/api/v1/conversations", json={})).json()["id"]
    chat_provider.replies = (RuntimeError(f"upstream rejected {API_KEY} for prompt 'my private prompt'"),)
    response = await client.post(
        f"/api/v1/conversations/{conversation}/messages/stream", json={"content": "my private prompt"}
    )
    assert response.status_code == 200
    output = log_stream.getvalue()
    failures = [entry for entry in _lines(log_stream) if entry["message"] == "Chat turn failed"]
    assert failures and failures[0]["exc_type"] == "RuntimeError"
    assert "my private prompt" not in output and API_KEY not in output
