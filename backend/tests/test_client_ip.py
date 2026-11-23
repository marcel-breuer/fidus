from starlette.requests import Request

from app.auth.client_ip import client_ip


def _request(*, client: tuple[str, int] | None, headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": headers,
            "client": client,
            "server": ("testserver", 80),
        }
    )


def test_private_peer_uses_real_ip_header() -> None:
    request = _request(
        client=("172.20.0.2", 1234),
        headers=[(b"x-real-ip", b"198.51.100.24")],
    )

    assert client_ip(request) == "198.51.100.24"


def test_public_peer_ignores_spoofed_real_ip_header() -> None:
    request = _request(
        client=("8.8.8.8", 1234),
        headers=[(b"x-real-ip", b"198.51.100.24")],
    )

    assert client_ip(request) == "8.8.8.8"


def test_missing_client_is_unknown() -> None:
    request = _request(client=None, headers=[])

    assert client_ip(request) == "unknown"
