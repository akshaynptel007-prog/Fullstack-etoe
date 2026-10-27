from functools import cache
from pathlib import Path

from redis.asyncio import BlockingConnectionPool, Redis

from app.config import Settings

_LUA_DIR = Path(__file__).parent / "lua"


def create_redis(settings: Settings) -> Redis:
    # A *blocking* pool: when every connection is busy, callers wait (bounded
    # by `timeout`) instead of failing with "Too many connections" — bursts are
    # absorbed rather than turned into 500s.
    pool = BlockingConnectionPool.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
        timeout=settings.redis_socket_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=30,
    )
    return Redis(connection_pool=pool)


@cache
def load_lua(name: str) -> str:
    return (_LUA_DIR / f"{name}.lua").read_text()
