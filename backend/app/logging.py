"""Structured JSON logging with a per-request correlation id.

The request id is generated at the edge (NGINX `$request_id`), accepted by
the API through `X-Request-ID`, propagated into RabbitMQ message headers and
re-bound by the worker, so one checkout can be traced across every hop.
"""

import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

import orjson

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "service": self.service,
            "msg": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        # Anything passed via `extra={...}` becomes a top-level field.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return orjson.dumps(payload, default=str).decode()


def configure_logging(level: str, service: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Uvicorn's access log duplicates our own access log middleware.
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("aio_pika", "aiormq", "asyncio"):
        logging.getLogger(noisy).setLevel("WARNING")
