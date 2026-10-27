"""Process-wide clients, created once in the app lifespan and shared by requests."""

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import create_engine, create_sessionmaker
from app.messaging import OrderPublisher
from app.redis_client import create_redis
from app.services.broadcaster import SaleBroadcaster
from app.services.checkout import CheckoutService
from app.services.inventory import InventoryGate
from app.services.order_status import OrderStatusStore
from app.services.rate_limit import RateLimiter
from app.services.sales import SaleCache, prime_open_sales


@dataclass
class Resources:
    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    gate: InventoryGate
    rate_limiter: RateLimiter
    order_status: OrderStatusStore
    publisher: OrderPublisher
    sale_cache: SaleCache
    broadcaster: SaleBroadcaster
    checkout: CheckoutService

    @classmethod
    async def create(cls, settings: Settings) -> "Resources":
        engine = create_engine(settings, application_name="flashsale-api")
        sessionmaker = create_sessionmaker(engine)
        redis = create_redis(settings)
        gate = InventoryGate(redis)
        order_status = OrderStatusStore(redis, ttl_seconds=settings.order_status_ttl_seconds)
        publisher = OrderPublisher(settings)
        await publisher.start()
        sale_cache = SaleCache(sessionmaker, settings.sale_cache_ttl_seconds)
        broadcaster = SaleBroadcaster(
            gate, interval_seconds=settings.broadcaster_interval_ms / 1000
        )

        await prime_open_sales(sessionmaker, gate)
        broadcaster.start()

        return cls(
            settings=settings,
            engine=engine,
            sessionmaker=sessionmaker,
            redis=redis,
            gate=gate,
            rate_limiter=RateLimiter(redis, enabled=settings.rate_limit_enabled),
            order_status=order_status,
            publisher=publisher,
            sale_cache=sale_cache,
            broadcaster=broadcaster,
            checkout=CheckoutService(
                gate=gate,
                publisher=publisher,
                order_status=order_status,
                sale_cache=sale_cache,
                sessionmaker=sessionmaker,
            ),
        )

    async def close(self) -> None:
        await self.broadcaster.stop()
        await self.publisher.close()
        await self.redis.aclose()
        await self.engine.dispose()
