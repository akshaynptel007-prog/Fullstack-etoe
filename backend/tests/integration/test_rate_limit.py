from redis.asyncio import Redis

from app.services.rate_limit import RateLimiter


async def test_sliding_window_blocks_after_limit(redis: Redis) -> None:
    limiter = RateLimiter(redis)
    results = [await limiter.hit("t", "ip-1", limit=3, window_ms=10_000) for _ in range(5)]
    assert [r.allowed for r in results] == [True, True, True, False, False]
    assert [r.remaining for r in results[:3]] == [2, 1, 0]
    assert 0 < results[3].retry_after_ms <= 10_000
    assert results[3].retry_after_seconds >= 1


async def test_identities_are_isolated(redis: Redis) -> None:
    limiter = RateLimiter(redis)
    for _ in range(2):
        await limiter.hit("t", "noisy", limit=2, window_ms=10_000)
    assert not (await limiter.hit("t", "noisy", limit=2, window_ms=10_000)).allowed
    assert (await limiter.hit("t", "quiet", limit=2, window_ms=10_000)).allowed


async def test_rejected_requests_do_not_grow_the_window(redis: Redis) -> None:
    limiter = RateLimiter(redis)
    for _ in range(50):
        await limiter.hit("t", "flood", limit=5, window_ms=10_000)
    assert await redis.zcard("rl:t:flood") == 5  # memory bounded by the limit


async def test_disabled_limiter_allows_everything(redis: Redis) -> None:
    limiter = RateLimiter(redis, enabled=False)
    assert all([(await limiter.hit("t", "x", limit=1, window_ms=1000)).allowed for _ in range(5)])
