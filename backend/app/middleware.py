"""Pure-ASGI middleware (no BaseHTTPMiddleware: it buffers and breaks SSE)."""

import logging
import re
import time
import uuid

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logging import request_id_var
from app.metrics import HTTP_LATENCY, HTTP_REQUESTS

log = logging.getLogger("app.access")

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_QUIET_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})


class RequestContextMiddleware:
    """Binds a request id, emits one structured access log line and RED metrics."""

    def __init__(self, app: ASGIApp, *, access_log: bool = True) -> None:
        self.app = app
        self.access_log = access_log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        status = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            elapsed = time.perf_counter() - started
            route = scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            method = scope["method"]
            HTTP_REQUESTS.labels(method, route_path, str(status)).inc()
            HTTP_LATENCY.labels(method, route_path).observe(elapsed)
            if self.access_log and scope["path"] not in _QUIET_PATHS:
                log.info(
                    "request",
                    extra={
                        "method": method,
                        "path": scope["path"],
                        "route": route_path,
                        "status": status,
                        "duration_ms": round(elapsed * 1000, 2),
                    },
                )
            request_id_var.reset(token)


def client_ip(request: Request, trusted_hops: int) -> str:
    """Resolve the real client IP behind `trusted_hops` proxies.

    Each trusted proxy *appends* the address it saw to X-Forwarded-For, so the
    client is the entry `trusted_hops` from the right. Anything further left
    is client-controlled and must not be trusted (it is trivially spoofed).
    """
    if trusted_hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            hops = [h.strip() for h in forwarded.split(",") if h.strip()]
            if hops:
                return hops[-trusted_hops] if len(hops) >= trusted_hops else hops[0]
    return request.client.host if request.client else "unknown"
