import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Inventory, Order, OrderStatus
from app.schemas import OrderReservedMessage
from app.worker.processor import persist_order
from tests.integration.conftest import SaleFactory


def _msg(
    sale_id: int, user_id: uuid.UUID, order_id: uuid.UUID | None = None
) -> OrderReservedMessage:
    return OrderReservedMessage(
        order_id=order_id or uuid.uuid4(),
        sale_id=sale_id,
        user_id=user_id,
        amount_cents=1000,
        reserved_at=datetime.now(UTC),
    )


async def _stock(sm: async_sessionmaker[AsyncSession], sale_id: int) -> int:
    async with sm() as s:
        value = await s.scalar(select(Inventory.stock).where(Inventory.sale_id == sale_id))
        assert value is not None
        return value


async def _count(sm: async_sessionmaker[AsyncSession], sale_id: int, status: OrderStatus) -> int:
    async with sm() as s:
        return int(
            await s.scalar(
                select(func.count()).where(Order.sale_id == sale_id, Order.status == status)
            )
            or 0
        )


async def test_confirms_and_decrements(
    sessionmaker: async_sessionmaker[AsyncSession], make_sale: SaleFactory, make_users
) -> None:
    sale = await make_sale(stock=2)
    [user] = await make_users(1)
    result = await persist_order(sessionmaker, _msg(sale.id, user.id))
    assert result.status is OrderStatus.CONFIRMED
    assert not result.replayed
    assert await _stock(sessionmaker, sale.id) == 1


async def test_redelivery_is_idempotent(
    sessionmaker: async_sessionmaker[AsyncSession], make_sale: SaleFactory, make_users
) -> None:
    sale = await make_sale(stock=5)
    [user] = await make_users(1)
    message = _msg(sale.id, user.id)
    first = await persist_order(sessionmaker, message)
    # Same message delivered again (e.g. worker crashed after COMMIT, before ACK).
    replays = await asyncio.gather(*(persist_order(sessionmaker, message) for _ in range(5)))
    assert first.status is OrderStatus.CONFIRMED
    assert all(r.replayed and r.status is OrderStatus.CONFIRMED for r in replays)
    assert await _stock(sessionmaker, sale.id) == 4  # decremented exactly once


async def test_database_guard_rejects_when_redis_over_admits(
    sessionmaker: async_sessionmaker[AsyncSession], make_sale: SaleFactory, make_users
) -> None:
    # Simulates Redis admitting more than the DB holds (e.g. after a Redis
    # failover re-primed the counter): the conditional UPDATE still says no.
    sale = await make_sale(stock=1)
    users = await make_users(3)
    results = [await persist_order(sessionmaker, _msg(sale.id, u.id)) for u in users]
    assert [r.status for r in results] == [
        OrderStatus.CONFIRMED,
        OrderStatus.REJECTED_SOLD_OUT,
        OrderStatus.REJECTED_SOLD_OUT,
    ]
    assert await _stock(sessionmaker, sale.id) == 0


async def test_one_confirmed_unit_per_user_enforced_by_db(
    sessionmaker: async_sessionmaker[AsyncSession], make_sale: SaleFactory, make_users
) -> None:
    sale = await make_sale(stock=5)
    [user] = await make_users(1)
    first = await persist_order(sessionmaker, _msg(sale.id, user.id))
    second = await persist_order(sessionmaker, _msg(sale.id, user.id))  # different order id
    assert first.status is OrderStatus.CONFIRMED
    assert second.status is OrderStatus.REJECTED_DUPLICATE
    assert await _count(sessionmaker, sale.id, OrderStatus.CONFIRMED) == 1
    assert await _stock(sessionmaker, sale.id) == 4
