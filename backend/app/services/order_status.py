"""Fast order-status lookups for the polling tracking URL.

Clients poll `GET /orders/{id}` while their order is queued. Serving those
polls from a Redis hash keeps tens of thousands of polls per second off
PostgreSQL; the database is only consulted on a cache miss.
"""

import time
import uuid
from dataclasses import dataclass
from typing import cast

from redis.asyncio import Redis

from app.models import OrderStatus


@dataclass(frozen=True, slots=True)
class CachedOrderStatus:
    order_id: uuid.UUID
    status: OrderStatus
    sale_id: int
    user_id: uuid.UUID
    updated_at_ms: int


class OrderStatusStore:
    def __init__(self, redis: Redis, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(order_id: uuid.UUID) -> str:
        return f"order:{order_id}"

    async def set(
        self, order_id: uuid.UUID, *, status: OrderStatus, sale_id: int, user_id: uuid.UUID
    ) -> None:
        key = self._key(order_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.hset(
                key,
                mapping={
                    "status": status.value,
                    "sale_id": sale_id,
                    "user_id": str(user_id),
                    "updated_at_ms": int(time.time() * 1000),
                },
            )
            pipe.expire(key, self._ttl)
            await pipe.execute()

    async def get(self, order_id: uuid.UUID) -> CachedOrderStatus | None:
        data = cast(dict[str, str], await self._redis.hgetall(self._key(order_id)))
        if not data:
            return None
        return CachedOrderStatus(
            order_id=order_id,
            status=OrderStatus(data["status"]),
            sale_id=int(data["sale_id"]),
            user_id=uuid.UUID(data["user_id"]),
            updated_at_ms=int(data["updated_at_ms"]),
        )
