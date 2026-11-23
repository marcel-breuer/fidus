import ipaddress

from fastapi import Request


def client_ip(request: Request) -> str:
    if request.client is None:
        return "unknown"

    peer = request.client.host
    try:
        peer_is_private = ipaddress.ip_address(peer).is_private
    except ValueError:
        peer_is_private = False

    if peer_is_private:
        return request.headers.get("x-real-ip") or peer
    return peer
