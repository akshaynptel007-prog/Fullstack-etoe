import asyncio
import uuid

from app.services.inventory import InventoryGate, ReserveCode
from tests.integration.conftest import SaleFactory


async def test_reserves_until_sold_out(gate: InventoryGate, make_sale: SaleFactory) -> None:
    sale = await make_sale(stock=3)
    codes = [(await gate.reserve(sale.id, uuid.uuid4(), uuid.uuid4())).code for _ in range(5)]
    assert codes == [ReserveCode.RESERVED] * 3 + [ReserveCode.SOLD_OUT] * 2
    assert await gate.remaining(sale.id) == 0


async def test_repeat_request_is_idempotent(gate: InventoryGate, make_sale: SaleFactory) -> None:
    sale = await make_sale(stock=5)
    user, first_order = uuid.uuid4(), uuid.uuid4()
    first = await gate.reserve(sale.id, user, first_order)
    again = await gate.reserve(sale.id, user, uuid.uuid4())
    assert first.code is ReserveCode.RESERVED
    assert again.code is ReserveCode.DUPLICATE
    assert again.order_id == first_order
    assert await gate.remaining(sale.id) == 4  # decremented exactly once


async def test_sale_window_uses_redis_clock(gate: InventoryGate, make_sale: SaleFactory) -> None:
    upcoming = await make_sale(stock=5, starts_in=3600)
    ended = await make_sale(stock=5, starts_in=-7200, duration_minutes=60)
    assert (
        await gate.reserve(upcoming.id, uuid.uuid4(), uuid.uuid4())
    ).code is ReserveCode.NOT_STARTED
    assert (await gate.reserve(ended.id, uuid.uuid4(), uuid.uuid4())).code is ReserveCode.ENDED
    assert await gate.remaining(upcoming.id) == 5


async def test_unprimed_sale_is_reported(gate: InventoryGate, make_sale: SaleFactory) -> None:
    sale = await make_sale(stock=5, prime=False)
    outcome = await gate.reserve(sale.id, uuid.uuid4(), uuid.uuid4())
    assert outcome.code is ReserveCode.NOT_INITIALISED


async def test_release_returns_unit_exactly_once(
    gate: InventoryGate, make_sale: SaleFactory
) -> None:
    sale = await make_sale(stock=1)
    user, order = uuid.uuid4(), uuid.uuid4()
    await gate.reserve(sale.id, user, order)
    assert await gate.remaining(sale.id) == 0
    assert await gate.release(sale.id, user, order) is True
    assert await gate.release(sale.id, user, order) is False  # double release is a no-op
    assert await gate.release(sale.id, user, uuid.uuid4()) is False  # wrong order id
    assert await gate.remaining(sale.id) == 1
    # The user may try again after a released reservation.
    assert (await gate.reserve(sale.id, user, uuid.uuid4())).code is ReserveCode.RESERVED


async def test_prime_without_overwrite_never_resets_live_counter(
    gate: InventoryGate, make_sale: SaleFactory
) -> None:
    sale = await make_sale(stock=10)
    await gate.reserve(sale.id, uuid.uuid4(), uuid.uuid4())
    written = await gate.prime(
        sale.id, stock=10, starts_at=sale.starts_at, ends_at=sale.ends_at, overwrite=False
    )
    assert written is False
    assert await gate.remaining(sale.id) == 9


async def test_concurrent_reservations_never_exceed_stock(
    gate: InventoryGate, make_sale: SaleFactory
) -> None:
    sale = await make_sale(stock=100)
    outcomes = await asyncio.gather(
        *(gate.reserve(sale.id, uuid.uuid4(), uuid.uuid4()) for _ in range(1000))
    )
    reserved = [o for o in outcomes if o.code is ReserveCode.RESERVED]
    assert len(reserved) == 100
    assert sorted(o.remaining for o in reserved) == list(range(100))  # every unit once
    assert await gate.remaining(sale.id) == 0
    assert await gate.reservations(sale.id) == 100
