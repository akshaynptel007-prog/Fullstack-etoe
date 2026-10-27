import secrets
from dataclasses import dataclass

from redis.asyncio import Redis

from app.redis_client import load_lua


@dataclass(frozen=True, slots=True)
class Limit:
    scope: str
    identity: str
    limit: int


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_ms: int
    denied_scope: str | None = None

    @property
    def retry_after_seconds(self) -> int:
        return max(1, -(-self.retry_after_ms // 1000))


class RateLimiter:
    """Distributed sliding-window limiter shared by every API replica."""

    def __init__(self, redis: Redis, *, enabled: bool = True) -> None:
        self._script = redis.register_script(load_lua("rate_limit"))
        self.enabled = enabled

    async def hit(self, group: str, *limits: Limit, window_ms: int) -> RateLimitResult:
        """Check (and record) several limits atomically in one Redis round trip."""
        if not self.enabled or not limits:
            return RateLimitResult(
                allowed=True, remaining=min((x.limit for x in limits), default=0), retry_after_ms=0
            )
        allowed, denied_index, remaining, retry_after = await self._script(
            keys=[f"rl:{{{group}}}:{x.scope}:{x.identity}" for x in limits],
            args=[window_ms, secrets.token_hex(8), *(x.limit for x in limits)],
        )
        return RateLimitResult(
            allowed=bool(allowed),
            remaining=int(remaining),
            retry_after_ms=int(retry_after),
            denied_scope=limits[int(denied_index) - 1].scope if denied_index else None,
        )
