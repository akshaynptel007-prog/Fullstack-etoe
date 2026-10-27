from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def create_engine(settings: Settings, *, application_name: str) -> AsyncEngine:
    # Pools are deliberately small: API replicas only read on the hot path and
    # all inventory writes funnel through a handful of worker connections.
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "server_settings": {
                "application_name": application_name,
                # Fail fast instead of queueing behind a lock: no request may
                # hang on the database during the spike.
                "statement_timeout": str(settings.db_statement_timeout_ms),
                "lock_timeout": "2000",
                "idle_in_transaction_session_timeout": "10000",
            },
            "command_timeout": settings.db_statement_timeout_ms / 1000 + 1,
        },
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
