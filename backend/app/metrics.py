import os

from fastapi import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

# --- API --------------------------------------------------------------------------
HTTP_REQUESTS = Counter(
    "flashsale_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "flashsale_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=_LATENCY_BUCKETS,
)
CHECKOUT_RESULTS = Counter("flashsale_checkout_total", "Checkout attempts by outcome", ["result"])
RATE_LIMITED = Counter("flashsale_rate_limited_total", "Requests rejected by rate limit", ["scope"])
SSE_CONNECTIONS = Gauge(
    "flashsale_sse_connections", "Open SSE sale-status streams", multiprocess_mode="livesum"
)
STOCK_REMAINING = Gauge(
    "flashsale_redis_stock_remaining",
    "Reservable units left in the Redis gate",
    ["sale_id"],
    multiprocess_mode="liveall",
)

# --- Worker -----------------------------------------------------------------------
WORKER_ORDERS = Counter("flashsale_worker_orders_total", "Orders processed by outcome", ["outcome"])
WORKER_LATENCY = Histogram(
    "flashsale_worker_processing_seconds", "DB transaction time per order", buckets=_LATENCY_BUCKETS
)
WORKER_QUEUE_LAG = Histogram(
    "flashsale_worker_queue_lag_seconds",
    "Reservation accepted -> order persisted",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
WORKER_RETRIES = Counter("flashsale_worker_retries_total", "Messages sent to the retry queue")
WORKER_DEAD_LETTERED = Counter(
    "flashsale_worker_dead_lettered_total", "Messages sent to the DLQ", ["reason"]
)
WORKER_INFLIGHT = Gauge("flashsale_worker_inflight", "Messages currently being processed")


def metrics_response() -> Response:
    if "PROMETHEUS_MULTIPROC_DIR" in os.environ:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
    else:
        registry = REGISTRY
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
