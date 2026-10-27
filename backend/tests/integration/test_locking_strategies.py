"""Executable comparison of inventory concurrency-control strategies.

Each test runs the same contended scenario — many concurrent buyers, few
units — against real PostgreSQL (READ COMMITTED, the default isolation):

* naive SELECT-then-UPDATE  -> OVERSELLS (the 540/500 trial-run bug)
* pessimistic FOR UPDATE    -> correct, but serialises buyers behind a row
                               lock; with a realistic request deadline they
                               time out while units go unsold (the trial-run
                               timeouts)
* optimistic compare-and-set-> correct, but burns retries under contention
* atomic conditional UPDATE -> correct, no retries, no lock waits beyond
                               one statement (what the worker ships)

Run with `-s` to print the timing table.
"""

import asyncio
import time
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Inventory, Order, OrderStatus
from app.schemas import OrderReservedMessage
from app.worker.processor import persist_order
from tests.integration.conftest import SaleFactory

STOCK = 10
BUYERS = 30

SELECT_STOCK = text("SELECT stock FROM inventory WHERE sale_id = :sale_id")
INSERT_ORDER = text(
    "INSERT INTO orders (id, sale_id, user_id, status, amount_cents, reserved_at) "
    "VALUES (:id, :sale_id, :user_id, 'CONFIRMED', 1000, now())"
)


async def _sold(sm: async_sessionmaker[AsyncSession], sale_id: int) -> tuple[int, int]:
    async with sm() as s:
        confirmed = await s.scalar(
            select(func.count()).where(
                Order.sale_id == sale_id, Order.status == OrderStatus.CONFIRMED
            )
        )
        stock = await s.scalar(select(Inventory.stock).where(Inventory.sale_id == sale_id))
        return int(confirmed or 0), int(stock or 0)


def _report(name: str, sold: int, stock_left: int, elapsed: float, **extra: int) -> None:
    details = " ".join(f"{k}={v}" for k, v in extra.items())
    print(
        f"\n  {name:<28} sold={sold:>3}/{STOCK} stock_left={stock_left:>3} "
        f"{elapsed * 1000:7.1f} ms {details}"
    )


async def test_naive_select_then_update_oversells(
    sessionmaker: async_sessionmaker[AsyncSession], make_sale: SaleFactory, make_users
) -> None:
    sale = await make_sale(stock=STOCK)
    users = await make_users(BUYERS)

    async def buy(user_id: uuid.UUID) -> None:
        async with sessionmaker() as s, s.begin():
            stock = await s.scalar(SELECT_STOCK, {"sale_id": sale.id})
            if stock is None or stock <= 0:
                return
            await asyncio.sleep(0.02)  # app work between read and write
            # Writes a value computed from a stale read: a lost update.
            await s.execute(
                text("UPDATE inventory SET stock = :stock WHERE sale_id = :sale_id"),
                {"stock": stock - 1, "sale_id": sale.id},
            )
            await s.execute(
                INSERT_ORDER, {"id": uuid.uuid4(), "sale_id": sale.id, "user_id": user_id}
            )

    started = time.perf_counter()
    await asyncio.gather(*(buy(u.id) for u in users))
    sold, left = await _sold(sessionmaker, sale.id)
    _report("naive SELECT-then-UPDATE", sold, left, time.perf_counter() - started)

    assert sold > STOCK, "expected the naive pattern to oversell"


async def test_pessimistic_locking_is_correct_but_times_out(
    sessionmaker: async_sessionmaker[AsyncSession], make_sale: SaleFactory, make_users
) -> None:
    sale = await make_sale(stock=STOCK)
    users = await make_users(BUYERS)
    timeouts = 0
    slowest = 0.0

    async def buy(user_id: uuid.UUID) -> None:
        nonlocal timeouts, slowest
        started = time.perf_counter()
        try:
            async with sessionmaker() as s, s.begin():
                # A 1 s request deadline, like any API behind a load balancer.
                await s.execute(text("SET LOCAL statement_timeout = '1000'"))
                stock = await s.scalar(
                    text("SELECT stock FROM inventory WHERE sale_id = :sale_id FOR UPDATE"),
                    {"sale_id": sale.id},
                )
                if stock is None or stock <= 0:
                    return
                await asyncio.sleep(0.3)  # same app work, now done while holding the lock
                await s.execute(
                    text("UPDATE inventory SET stock = stock - 1 WHERE sale_id = :sale_id"),
                    {"sale_id": sale.id},
                )
                await s.execute(
                    INSERT_ORDER, {"id": uuid.uuid4(), "sale_id": sale.id, "user_id": user_id}
                )
        except DBAPIError as exc:
            if "statement timeout" not in str(exc).lower():
                raise
            timeouts += 1  # the buyer queued behind the row lock past the deadline
        finally:
            slowest = max(slowest, time.perf_counter() - started)

    started = time.perf_counter()
    await asyncio.gather(*(buy(u.id) for u in users))
    sold, left = await _sold(sessionmaker, sale.id)
    _report(
        "pessimistic FOR UPDATE",
        sold,
        left,
        time.perf_counter() - started,
        timeouts=timeouts,
        slowest_ms=int(slowest * 1000),
    )

    assert sold <= STOCK  # never oversells...
    assert sold + left == STOCK
    assert timeouts > 0  # ...but serialises buyers until they time out (units left unsold)


async def test_optimistic_locking_is_correct_but_retries(
    sessionmaker: async_sessionmaker[AsyncSession], make_sale: SaleFactory, make_users
) -> None:
    sale = await make_sale(stock=STOCK)
    users = await make_users(BUYERS)
    retries = 0

    async def buy(user_id: uuid.UUID) -> None:
        nonlocal retries
        for _ in range(100):
            async with sessionmaker() as s, s.begin():
                seen = await s.scalar(SELECT_STOCK, {"sale_id": sale.id})
                if seen is None or seen <= 0:
                    return
                await asyncio.sleep(0.005)
                swapped = (
                    await s.execute(
                        text(
                            "UPDATE inventory SET stock = stock - 1 "
                            "WHERE sale_id = :sale_id AND stock = :seen RETURNING stock"
                        ),
                        {"sale_id": sale.id, "seen": seen},
                    )
                ).first()
                if swapped is None:
                    retries += 1  # someone else won the race; re-read and retry
                    continue
                await s.execute(
                    INSERT_ORDER, {"id": uuid.uuid4(), "sale_id": sale.id, "user_id": user_id}
                )
                return
        pytest.fail("optimistic buyer starved")

    started = time.perf_counter()
    await asyncio.gather(*(buy(u.id) for u in users))
    sold, left = await _sold(sessionmaker, sale.id)
    _report(
        "optimistic compare-and-set", sold, left, time.perf_counter() - started, retries=retries
    )

    assert sold == STOCK
    assert left == 0
    assert retries > 0


async def test_atomic_conditional_update_is_correct_without_retries(
    sessionmaker: async_sessionmaker[AsyncSession], make_sale: SaleFactory, make_users
) -> None:
    sale = await make_sale(stock=STOCK)
    users = await make_users(BUYERS)

    def message(user_id: uuid.UUID) -> OrderReservedMessage:
        return OrderReservedMessage(
            order_id=uuid.uuid4(),
            sale_id=sale.id,
            user_id=user_id,
            amount_cents=1000,
            reserved_at=datetime.now(UTC),
        )

    started = time.perf_counter()
    results = await asyncio.gather(*(persist_order(sessionmaker, message(u.id)) for u in users))
    sold, left = await _sold(sessionmaker, sale.id)
    _report("atomic conditional UPDATE", sold, left, time.perf_counter() - started)

    assert sold == STOCK
    assert left == 0
    assert sum(r.status is OrderStatus.REJECTED_SOLD_OUT for r in results) == BUYERS - STOCK
