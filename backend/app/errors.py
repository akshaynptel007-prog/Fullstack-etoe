import logging

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


class AppError(Exception):
    """An expected failure mapped to a stable machine-readable error code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}


def error_payload(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        error_payload(exc.code, exc.message), status_code=exc.status_code, headers=exc.headers
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error", exc_info=exc)
    return JSONResponse(
        error_payload("INTERNAL_ERROR", "Something went wrong. Please retry."),
        status_code=500,
        headers={"Retry-After": "1"},
    )
