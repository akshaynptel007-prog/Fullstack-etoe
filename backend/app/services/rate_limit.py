import secrets
from dataclasses import dataclass

from redis.asyncio import Redis

from app.redis_client import load_lua


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_ms: int

    @property
    def retry_after_seconds(self) -> int:
        return max(1, -(-self.retry_after_ms // 1000))


class RateLimiter:
    """Distributed sliding-window limiter shared by every API replica."""

    def __init__(self, redis: Redis, *, enabled: bool = True) -> None:
        self._script = redis.register_script(load_lua("rate_limit"))
        self.enabled = enabled

    async def hit(
        self, scope: str, identity: str, *, limit: int, window_ms: int
    ) -> RateLimitResult:
        if not self.enabled:
            return RateLimitResult(allowed=True, remaining=limit, retry_after_ms=0)
        allowed, remaining, retry_after = await self._script(
            keys=[f"rl:{scope}:{identity}"],
            args=[limit, window_ms, secrets.token_hex(8)],
        )
        return RateLimitResult(
            allowed=bool(allowed), remaining=int(remaining), retry_after_ms=int(retry_after)
        )
