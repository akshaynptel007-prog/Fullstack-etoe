from redis.asyncio import Redis

from app.services.rate_limit import Limit, RateLimiter


async def test_sliding_window_blocks_after_limit(redis: Redis) -> None:
    limiter = RateLimiter(redis)
    results = [
        await limiter.hit("t", Limit("ip", "1.1.1.1", 3), window_ms=10_000) for _ in range(5)
    ]
    assert [r.allowed for r in results] == [True, True, True, False, False]
    assert [r.remaining for r in results[:3]] == [2, 1, 0]
    assert 0 < results[3].retry_after_ms <= 10_000
    assert results[3].retry_after_seconds >= 1
    assert results[3].denied_scope == "ip"


async def test_identities_are_isolated(redis: Redis) -> None:
    limiter = RateLimiter(redis)
    for _ in range(2):
        await limiter.hit("t", Limit("ip", "noisy", 2), window_ms=10_000)
    assert not (await limiter.hit("t", Limit("ip", "noisy", 2), window_ms=10_000)).allowed
    assert (await limiter.hit("t", Limit("ip", "quiet", 2), window_ms=10_000)).allowed


async def test_multiple_limits_are_checked_atomically(redis: Redis) -> None:
    limiter = RateLimiter(redis)
    ip_limit = 100
    # Same IP, one user exhausts their personal limit of 2...
    for _ in range(2):
        assert (
            await limiter.hit(
                "t", Limit("ip", "nat", ip_limit), Limit("user", "u1", 2), window_ms=10_000
            )
        ).allowed
    denied = await limiter.hit(
        "t", Limit("ip", "nat", ip_limit), Limit("user", "u1", 2), window_ms=10_000
    )
    assert not denied.allowed
    assert denied.denied_scope == "user"
    # ...a denied request consumes nothing, so a neighbour behind the same NAT
    # IP is unaffected and the IP window only counts admitted requests.
    other = await limiter.hit(
        "t", Limit("ip", "nat", ip_limit), Limit("user", "u2", 2), window_ms=10_000
    )
    assert other.allowed
    assert await redis.zcard("rl:{t}:ip:nat") == 3


async def test_rejected_requests_do_not_grow_the_window(redis: Redis) -> None:
    limiter = RateLimiter(redis)
    for _ in range(50):
        await limiter.hit("t", Limit("ip", "flood", 5), window_ms=10_000)
    assert await redis.zcard("rl:{t}:ip:flood") == 5  # memory bounded by the limit


async def test_disabled_limiter_allows_everything(redis: Redis) -> None:
    limiter = RateLimiter(redis, enabled=False)
    results = [await limiter.hit("t", Limit("ip", "x", 1), window_ms=1000) for _ in range(5)]
    assert all(r.allowed for r in results)
