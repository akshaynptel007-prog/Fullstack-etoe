"""Persist one reserved order — the only code that writes inventory.

Exactly-once *effect* on top of at-least-once delivery:

1. INSERT the order keyed by the API-generated id, ON CONFLICT DO NOTHING.
   A redelivered message hits the conflict and becomes a no-op replay, so a
   crash between COMMIT and ACK can never decrement stock twice.
2. Atomic, conditional decrement — no SELECT first, no FOR UPDATE:

       UPDATE inventory SET stock = stock - 1
        WHERE sale_id = :sale_id AND stock > 0
    RETURNING stock

   PostgreSQL evaluates `stock > 0` against the latest committed row version
   while holding the row lock, so concurrent workers serialise on the row
   for microseconds and the predicate can never be satisfied by a stale
   read. Zero rows updated => sold out => the order is rejected.
3. COMMIT. The row lock is held only for steps 2-3, a few hundred µs.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from aio_pika.abc import AbstractExchange, AbstractIncomingMessage
from pydantic import ValidationError
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.logging import request_id_var
from app.messaging import ROUTING_KEY, build_order_message
from app.metrics import (
    WORKER_DEAD_LETTERED,
    WORKER_INFLIGHT,
    WORKER_LATENCY,
    WORKER_ORDERS,
    WORKER_QUEUE_LAG,
    WORKER_RETRIES,
)
from app.models import Order, OrderStatus
from app.schemas import OrderReservedMessage
from app.services.inventory import InventoryGate
from app.services.order_status import OrderStatusStore

log = logging.getLogger(__name__)

ONE_CONFIRMED_PER_USER = "uq_orders_one_confirmed_per_user"

DECREMENT_STOCK = text(
    "UPDATE inventory SET stock = stock - 1, updated_at = now() "
    "WHERE sale_id = :sale_id AND stock > 0 "
    "RETURNING stock"
)


@dataclass(frozen=True, slots=True)
class PersistResult:
    status: OrderStatus
    replayed: bool


def _violates(exc: IntegrityError, constraint: str) -> bool:
    cause = getattr(exc.orig, "__cause__", None)
    name = getattr(cause, "constraint_name", None)
    return name == constraint or constraint in str(exc.orig)


async def persist_order(
    sessionmaker: async_sessionmaker[AsyncSession], msg: OrderReservedMessage
) -> PersistResult:
    values = {
        "id": msg.order_id,
        "sale_id": msg.sale_id,
        "user_id": msg.user_id,
        "amount_cents": msg.amount_cents,
        "reserved_at": msg.reserved_at,
        "request_id": msg.request_id,
    }
    async with sessionmaker() as session:
        try:
            async with session.begin():
                inserted = await session.scalar(
                    insert(Order)
                    .values(**values, status=OrderStatus.CONFIRMED)
                    .on_conflict_do_nothing(index_elements=[Order.id])
                    .returning(Order.id)
                )
                if inserted is None:
                    existing = await session.scalar(
                        select(Order.status).where(Order.id == msg.order_id)
                    )
                    return PersistResult(existing or OrderStatus.FAILED, replayed=True)

                decremented = (
                    await session.execute(DECREMENT_STOCK, {"sale_id": msg.sale_id})
                ).first()
                if decremented is None:
                    await session.execute(
                        update(Order)
                        .where(Order.id == msg.order_id)
                        .values(status=OrderStatus.REJECTED_SOLD_OUT)
                    )
                    return PersistResult(OrderStatus.REJECTED_SOLD_OUT, replayed=False)
                return PersistResult(OrderStatus.CONFIRMED, replayed=False)
        except IntegrityError as exc:
            if not _violates(exc, ONE_CONFIRMED_PER_USER):
                raise
        # The user already owns a confirmed unit of this sale. Only reachable
        # if Redis lost its buyer set; the database still says no.
        async with session.begin():
            await session.execute(
                insert(Order)
                .values(**values, status=OrderStatus.REJECTED_DUPLICATE)
                .on_conflict_do_nothing(index_elements=[Order.id])
            )
        return PersistResult(OrderStatus.REJECTED_DUPLICATE, replayed=False)


class OrderProcessor:
    def __init__(
        self,
        *,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        gate: InventoryGate,
        order_status: OrderStatusStore,
        retry_exchange: AbstractExchange,
    ) -> None:
        self._settings = settings
        self._sessionmaker = sessionmaker
        self._gate = gate
        self._order_status = order_status
        self._retry_exchange = retry_exchange

    async def handle(self, message: AbstractIncomingMessage) -> None:
        token = request_id_var.set(message.correlation_id)
        WORKER_INFLIGHT.inc()
        try:
            await self._handle(message)
        finally:
            WORKER_INFLIGHT.dec()
            request_id_var.reset(token)

    async def _handle(self, message: AbstractIncomingMessage) -> None:
        try:
            payload = OrderReservedMessage.model_validate_json(message.body)
        except ValidationError:
            log.error("poison message, dead-lettering", extra={"message_id": message.message_id})
            WORKER_DEAD_LETTERED.labels("invalid_payload").inc()
            await message.reject(requeue=False)
            return

        started = time.perf_counter()
        try:
            result = await persist_order(self._sessionmaker, payload)
            await self._order_status.set(
                payload.order_id,
                status=result.status,
                sale_id=payload.sale_id,
                user_id=payload.user_id,
            )
        except (IntegrityError, DataError) as exc:
            # Deterministic failure (e.g. the sale/user no longer exists):
            # retrying cannot help.
            await self._give_up(payload, message, reason="integrity_error", exc=exc)
            return
        except Exception as exc:
            # DB/Redis blip, timeout, failover: safe to retry because
            # persist_order is idempotent.
            await self._retry_or_give_up(payload, message, exc)
            return

        WORKER_LATENCY.observe(time.perf_counter() - started)
        WORKER_QUEUE_LAG.observe(
            max(0.0, (datetime.now(UTC) - payload.reserved_at).total_seconds())
        )
        WORKER_ORDERS.labels("replayed" if result.replayed else result.status.value.lower()).inc()
        log.info(
            "order processed",
            extra={
                "order_id": str(payload.order_id),
                "sale_id": payload.sale_id,
                "status": result.status.value,
                "replayed": result.replayed,
            },
        )
        await message.ack()

    async def _retry_or_give_up(
        self, payload: OrderReservedMessage, message: AbstractIncomingMessage, exc: Exception
    ) -> None:
        previous = (message.headers or {}).get("x-attempt", 0)
        attempt = (previous if isinstance(previous, int) else 0) + 1
        if attempt > self._settings.worker_max_retries:
            await self._give_up(payload, message, reason="retries_exhausted", exc=exc)
            return
        log.warning(
            "transient failure, scheduling retry",
            extra={"order_id": str(payload.order_id), "attempt": attempt, "error": repr(exc)},
        )
        WORKER_RETRIES.inc()
        # Publish the copy (confirmed) BEFORE acking the original: a crash in
        # between yields a duplicate, which the idempotent insert absorbs.
        await self._retry_exchange.publish(
            build_order_message(payload, attempt=attempt), routing_key=ROUTING_KEY
        )
        await message.ack()

    async def _give_up(
        self,
        payload: OrderReservedMessage,
        message: AbstractIncomingMessage,
        *,
        reason: str,
        exc: Exception,
    ) -> None:
        log.error(
            "order failed permanently, dead-lettering",
            extra={"order_id": str(payload.order_id), "reason": reason, "error": repr(exc)},
        )
        WORKER_DEAD_LETTERED.labels(reason).inc()
        try:
            # Nothing was committed, so hand the unit back to the pool and
            # tell the user, rather than leaving them on PENDING forever.
            await self._gate.release(payload.sale_id, payload.user_id, payload.order_id)
            await self._order_status.set(
                payload.order_id,
                status=OrderStatus.FAILED,
                sale_id=payload.sale_id,
                user_id=payload.user_id,
            )
        except Exception:
            log.exception("compensation failed", extra={"order_id": str(payload.order_id)})
        await message.reject(requeue=False)
