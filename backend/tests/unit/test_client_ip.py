import pytest
from starlette.requests import Request

from app.middleware import client_ip


def _request(xff: str | None, peer: str = "10.0.0.9") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


@pytest.mark.parametrize(
    ("xff", "hops", "expected"),
    [
        # Local: NGINX appends the real peer -> rightmost entry.
        ("203.0.113.7", 1, "203.0.113.7"),
        # A spoofed left-most entry is ignored.
        ("6.6.6.6, 203.0.113.7", 1, "203.0.113.7"),
        # AWS: CloudFront appends the viewer, ALB appends CloudFront's edge IP.
        ("6.6.6.6, 203.0.113.7, 130.176.0.1", 2, "203.0.113.7"),
        # Fewer hops than expected: best effort.
        ("203.0.113.7", 2, "203.0.113.7"),
    ],
)
def test_client_ip_uses_trusted_hop(xff: str, hops: int, expected: str) -> None:
    assert client_ip(_request(xff), hops) == expected


def test_client_ip_falls_back_to_peer() -> None:
    assert client_ip(_request(None), 1) == "10.0.0.9"
    assert client_ip(_request("1.2.3.4"), 0) == "10.0.0.9"
