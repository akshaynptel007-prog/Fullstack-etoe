import asyncio
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse

from app.deps import ResourcesDep
from app.errors import AppError
from app.schemas import SaleOut, SaleStatusOut, ServerTimeOut
from app.services.sales import SaleInfo, build_status

router = APIRouter(tags=["sales"])

_TERMINAL_STATES = frozenset({"sold_out", "ended"})


async def _get_sale(resources: ResourcesDep, sale_id: int) -> SaleInfo:
    sale = await resources.sale_cache.get(sale_id)
    if sale is None:
        raise AppError(404, "SALE_NOT_FOUND", "This sale does not exist.")
    return sale


@router.get("/time", summary="Server clock, for client-side countdown sync")
async def server_time(response: Response) -> ServerTimeOut:
    response.headers["Cache-Control"] = "no-store"
    return ServerTimeOut(server_time_ms=int(time.time() * 1000))


@router.get("/sales/current", summary="The live or next upcoming sale")
async def current_sale(resources: ResourcesDep, response: Response) -> SaleOut:
    sale = await resources.sale_cache.current()
    if sale is None:
        raise AppError(404, "NO_SALE", "There is no sale scheduled.")
    response.headers["Cache-Control"] = "public, max-age=5"
    return sale.to_out()


@router.get("/sales/{sale_id}")
async def get_sale(sale_id: int, resources: ResourcesDep, response: Response) -> SaleOut:
    sale = await _get_sale(resources, sale_id)
    response.headers["Cache-Control"] = "public, max-age=5"
    return sale.to_out()


@router.get(
    "/sales/{sale_id}/status",
    summary="Live stock snapshot (polling fallback; micro-cached 1 s at the edge)",
)
async def sale_status(sale_id: int, resources: ResourcesDep, response: Response) -> SaleStatusOut:
    sale = await _get_sale(resources, sale_id)
    # Public, identical for every viewer -> NGINX/CloudFront cache it for 1 s
    # and collapse concurrent misses, so 100k pollers cost ~1 origin hit/s.
    response.headers["Cache-Control"] = "public, max-age=1, stale-while-revalidate=1"
    return build_status(sale, await resources.gate.remaining(sale_id))


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


@router.get(
    "/sales/{sale_id}/events",
    summary="Server-Sent Events stream of live stock",
    response_class=StreamingResponse,
)
async def sale_events(sale_id: int, resources: ResourcesDep) -> StreamingResponse:
    sale = await _get_sale(resources, sale_id)
    settings = resources.settings
    broadcaster = resources.broadcaster
    if broadcaster.connection_count >= settings.sse_max_connections_per_process:
        # Shed load: the client falls back to polling the cached status endpoint.
        raise AppError(
            503,
            "STREAM_CAPACITY",
            "Live updates are busy; polling instead.",
            headers={"Retry-After": "5"},
        )

    queue = broadcaster.subscribe(sale_id)
    initial = await resources.gate.remaining(sale_id)

    async def stream() -> AsyncIterator[str]:
        try:
            # Clients reconnect after `retry` ms (plus their own jitter).
            yield "retry: 3000\n\n"
            remaining = initial
            while True:
                status = build_status(sale, remaining)
                yield _sse("status", status.model_dump_json())
                if status.state in _TERMINAL_STATES:
                    yield _sse("end", status.state)
                    return
                try:
                    remaining = await asyncio.wait_for(
                        queue.get(), timeout=settings.sse_heartbeat_seconds
                    )
                except TimeoutError:
                    # Heartbeat keeps ALB/CloudFront/NGINX idle timers from
                    # closing the stream; the loop re-sends the status too,
                    # which also flips "upcoming" -> "live" at start time.
                    yield ": keep-alive\n\n"
        finally:
            broadcaster.unsubscribe(sale_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
