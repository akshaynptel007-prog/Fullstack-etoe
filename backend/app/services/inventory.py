"""Redis inventory gate: the admission-control layer in front of PostgreSQL.

100k requests hit this gate; at most `total_stock` of them get through. Only
those few hundred reach RabbitMQ and the database, which is what removes the
row-lock storm and the timeouts seen in the trial runs.
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime

from redis.asyncio import Redis

from app.redis_client import load_lua


class ReserveCode(enum.IntEnum):
    RESERVED = 1
    DUPLICATE = 2
    SOLD_OUT = 0
    NOT_INITIALISED = -1
    NOT_STARTED = -2
    ENDED = -3


@dataclass(frozen=True, slots=True)
class ReserveOutcome:
    code: ReserveCode
    order_id: uuid.UUID | None
    remaining: int


@dataclass(frozen=True, slots=True)
class SaleKeys:
    stock: str
    buyers: str
    meta: str

    @classmethod
    def for_sale(cls, sale_id: int) -> "SaleKeys":
        # `{sale_id}` is a Redis Cluster hash tag: all three keys land on the
        # same slot, which multi-key Lua scripts require.
        tag = f"sale:{{{sale_id}}}"
        return cls(stock=f"{tag}:stock", buyers=f"{tag}:buyers", meta=f"{tag}:meta")


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


class InventoryGate:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._reserve = redis.register_script(load_lua("reserve"))
        self._release = redis.register_script(load_lua("release"))

    async def reserve(
        self, sale_id: int, user_id: uuid.UUID, order_id: uuid.UUID
    ) -> ReserveOutcome:
        keys = SaleKeys.for_sale(sale_id)
        code, oid, remaining = await self._reserve(
            keys=[keys.stock, keys.buyers, keys.meta], args=[str(user_id), str(order_id)]
        )
        return ReserveOutcome(
            code=ReserveCode(int(code)),
            order_id=uuid.UUID(oid) if oid else None,
            remaining=int(remaining),
        )

    async def release(self, sale_id: int, user_id: uuid.UUID, order_id: uuid.UUID) -> bool:
        keys = SaleKeys.for_sale(sale_id)
        result = await self._release(
            keys=[keys.stock, keys.buyers], args=[str(user_id), str(order_id)]
        )
        return int(result) >= 0

    async def prime(
        self,
        sale_id: int,
        *,
        stock: int,
        starts_at: datetime,
        ends_at: datetime,
        overwrite: bool,
    ) -> bool:
        """Load a sale's countdown token into Redis.

        `overwrite=False` (startup / self-healing) only sets the stock if it is
        missing, so a restarting replica can never reset a live counter.
        `overwrite=True` is the admin "reset sale" path.
        Returns True if the stock value was written.
        """
        keys = SaleKeys.for_sale(sale_id)
        async with self._redis.pipeline(transaction=True) as pipe:
            if overwrite:
                pipe.delete(keys.buyers)
                pipe.set(keys.stock, stock)
            else:
                pipe.set(keys.stock, stock, nx=True)
            pipe.hset(
                keys.meta,
                mapping={"starts_at_ms": _ms(starts_at), "ends_at_ms": _ms(ends_at)},
            )
            results = await pipe.execute()
        return bool(results[1] if overwrite else results[0])

    async def remaining(self, sale_id: int) -> int | None:
        value = await self._redis.get(SaleKeys.for_sale(sale_id).stock)
        return int(value) if value is not None else None

    async def remaining_many(self, sale_ids: list[int]) -> dict[int, int | None]:
        if not sale_ids:
            return {}
        values = await self._redis.mget([SaleKeys.for_sale(s).stock for s in sale_ids])
        return {
            sid: int(v) if v is not None else None for sid, v in zip(sale_ids, values, strict=True)
        }

    async def reservations(self, sale_id: int) -> int:
        return int(await self._redis.hlen(SaleKeys.for_sale(sale_id).buyers))

    async def set_stock(self, sale_id: int, stock: int) -> None:
        await self._redis.set(SaleKeys.for_sale(sale_id).stock, stock)
