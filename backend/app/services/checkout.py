"""The hot path: everything a checkout request does before answering 202.

    rate limit (Redis) -> reserve token (Redis Lua) -> publish (RabbitMQ) -> 202

No database access, no locks, no blocking calls: the request costs a few
sub-millisecond Redis round-trips plus one broker confirm, so a stateless
replica can answer thousands of them per second. The heavy, durable write
happens asynchronously in the worker.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.errors import AppError
from app.messaging import OrderPublisher
from app.metrics import CHECKOUT_RESULTS
from app.models import OrderStatus
from app.schemas import OrderReservedMessage
from app.services.inventory import InventoryGate, ReserveCode, ReserveOutcome
from app.services.order_status import OrderStatusStore
from app.services.sales import SaleCache, SaleInfo, prime_sale

log = logging.getLogger(__name__)

# How long a process trusts "sold out" before asking Redis again. Short, so an
# admin restock or a released reservation is picked up almost immediately.
_SOLD_OUT_MEMO_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    order_id: uuid.UUID
    duplicate: bool
    remaining: int


class CheckoutService:
    def __init__(
        self,
        *,
        gate: InventoryGate,
        publisher: OrderPublisher,
        order_status: OrderStatusStore,
        sale_cache: SaleCache,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        self._gate = gate
        self._publisher = publisher
        self._order_status = order_status
        self._sale_cache = sale_cache
        self._sessionmaker = sessionmaker
        self._sold_out_until: dict[int, float] = {}

    def recently_sold_out(self, sale_id: int) -> bool:
        return self._sold_out_until.get(sale_id, 0.0) > time.monotonic()

    async def checkout(
        self, *, sale_id: int, user_id: uuid.UUID, request_id: str | None
    ) -> CheckoutResult:
        sale = await self._sale_cache.get(sale_id)
        if sale is None:
            raise AppError(404, "SALE_NOT_FOUND", "This sale does not exist.")

        order_id = uuid.uuid4()
        outcome = await self._reserve(sale, user_id, order_id)
        CHECKOUT_RESULTS.labels(outcome.code.name.lower()).inc()

        match outcome.code:
            case ReserveCode.RESERVED:
                await self._enqueue(sale, user_id, order_id, request_id)
                return CheckoutResult(order_id, duplicate=False, remaining=outcome.remaining)
            case ReserveCode.DUPLICATE:
                assert outcome.order_id is not None
                return CheckoutResult(outcome.order_id, duplicate=True, remaining=outcome.remaining)
            case ReserveCode.SOLD_OUT:
                self._sold_out_until[sale.id] = time.monotonic() + _SOLD_OUT_MEMO_SECONDS
                raise AppError(409, "SOLD_OUT", "Sold out — all units have been reserved.")
            case ReserveCode.NOT_STARTED:
                raise AppError(409, "SALE_NOT_STARTED", "The sale has not started yet.")
            case ReserveCode.ENDED:
                raise AppError(409, "SALE_ENDED", "The sale has ended.")
            case ReserveCode.NOT_INITIALISED:
                raise AppError(
                    503,
                    "SALE_WARMING_UP",
                    "The sale is warming up. Please retry.",
                    headers={"Retry-After": "1"},
                )

    async def _reserve(
        self, sale: SaleInfo, user_id: uuid.UUID, order_id: uuid.UUID
    ) -> ReserveOutcome:
        outcome = await self._gate.reserve(sale.id, user_id, order_id)
        if outcome.code is ReserveCode.NOT_INITIALISED:
            # Redis lost the token (restart without persistence / failover).
            # Re-prime from PostgreSQL with SET NX and retry once. Any
            # over-admission this could cause is caught by the DB guard.
            async with self._sessionmaker() as session:
                await prime_sale(session, self._gate, sale.id)
            outcome = await self._gate.reserve(sale.id, user_id, order_id)
        return outcome

    async def _enqueue(
        self, sale: SaleInfo, user_id: uuid.UUID, order_id: uuid.UUID, request_id: str | None
    ) -> None:
        # Status first, publish second: the worker's final status can then
        # never be overwritten by a late PENDING.
        await self._order_status.set(
            order_id, status=OrderStatus.PENDING, sale_id=sale.id, user_id=user_id
        )
        message = OrderReservedMessage(
            order_id=order_id,
            sale_id=sale.id,
            user_id=user_id,
            amount_cents=sale.product.price_cents,
            reserved_at=datetime.now(UTC),
            request_id=request_id,
        )
        try:
            await self._publisher.publish(message)
        except Exception as exc:
            # The broker did not take responsibility for the order: undo the
            # reservation so the unit goes back on sale, and tell the client
            # to retry. Fails safe: worst case is a brief undersell, never an
            # oversell (see docs/concurrency.md, "ambiguous publish").
            log.exception(
                "publish failed, releasing reservation", extra={"order_id": str(order_id)}
            )
            await self._gate.release(sale.id, user_id, order_id)
            await self._order_status.set(
                order_id, status=OrderStatus.FAILED, sale_id=sale.id, user_id=user_id
            )
            CHECKOUT_RESULTS.labels("queue_unavailable").inc()
            raise AppError(
                503,
                "QUEUE_UNAVAILABLE",
                "We could not queue your order. Please retry.",
                headers={"Retry-After": "2"},
            ) from exc
