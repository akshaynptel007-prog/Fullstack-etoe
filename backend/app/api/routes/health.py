from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.deps import ResourcesDep
from app.metrics import metrics_response

router = APIRouter(tags=["ops"])


@router.get("/healthz", summary="Liveness: the process is up")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness: dependencies are reachable")
async def readyz(resources: ResourcesDep) -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        async with resources.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"
    try:
        await resources.redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    checks["rabbitmq"] = "ok" if resources.publisher.is_connected else "error: disconnected"

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status_code=200 if healthy else 503,
    )


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return metrics_response()
