import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, auth, checkout, health, orders, sales
from app.config import Settings, get_settings
from app.errors import AppError, app_error_handler, unhandled_error_handler
from app.logging import configure_logging
from app.middleware import RequestContextMiddleware
from app.resources import Resources

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, service="api")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.resources = await Resources.create(settings)
        log.info("api started", extra={"env": settings.app_env})
        try:
            yield
        finally:
            await app.state.resources.close()
            log.info("api stopped")

    app = FastAPI(
        title="Flash Sale API",
        version="1.0.0",
        description=(
            "Checkout pipeline for a 500-unit flash sale under a 100k-request spike. "
            "Redis Lua inventory tokens gate admission, RabbitMQ decouples the write path, "
            "and PostgreSQL's conditional UPDATE is the final guard against overselling."
        ),
        lifespan=lifespan,
        docs_url=None if settings.is_production else f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else f"{API_PREFIX}/openapi.json",
    )

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Admin-Key"],
            expose_headers=["Location", "Retry-After", "X-Request-ID"],
        )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    for module in (auth, sales, checkout, orders, admin):
        app.include_router(module.router, prefix=API_PREFIX)
    return app
