import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from app.errors import AppError
from app.models import Inventory, Order, OrderStatus, Product, Sale
from app.schemas import ProductOut, SaleOut, SaleState, SaleStatsOut, SaleStatusOut
from app.services.inventory import InventoryGate

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SaleInfo:
    id: int
    name: str
    starts_at: datetime
    ends_at: datetime
    total_stock: int
    product: ProductOut

    @classmethod
    def from_model(cls, sale: Sale) -> "SaleInfo":
        p = sale.product
        return cls(
            id=sale.id,
            name=sale.name,
            starts_at=sale.starts_at,
            ends_at=sale.ends_at,
            total_stock=sale.total_stock,
            product=ProductOut(
                id=p.id,
                sku=p.sku,
                name=p.name,
                description=p.description,
                price_cents=p.price_cents,
                currency=p.currency,
            ),
        )

    def to_out(self) -> SaleOut:
        return SaleOut(
            id=self.id,
            name=self.name,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
            total_stock=self.total_stock,
            product=self.product,
        )


def utcnow() -> datetime:
    return datetime.now(UTC)


def compute_state(sale: SaleInfo, remaining: int | None, now: datetime) -> SaleState:
    if now >= sale.ends_at:
        return "ended"
    if remaining is not None and remaining <= 0:
        return "sold_out"
    if now < sale.starts_at:
        return "upcoming"
    return "live"


def build_status(sale: SaleInfo, remaining: int | None) -> SaleStatusOut:
    now = utcnow()
    left = sale.total_stock if remaining is None else max(remaining, 0)
    return SaleStatusOut(
        sale_id=sale.id,
        state=compute_state(sale, left, now),
        remaining=left,
        total_stock=sale.total_stock,
        starts_at=sale.starts_at,
        ends_at=sale.ends_at,
        server_time_ms=int(now.timestamp() * 1000),
    )


# --- Queries (each is ONE round trip: product is joined, never lazy-loaded) -------
async def load_sale(session: AsyncSession, sale_id: int) -> SaleInfo | None:
    sale = await session.scalar(
        select(Sale).options(joinedload(Sale.product)).where(Sale.id == sale_id)
    )
    return SaleInfo.from_model(sale) if sale else None


async def load_current_sale(session: AsyncSession) -> SaleInfo | None:
    """The sale that is live or upcoming next; otherwise the most recent one."""
    base = select(Sale).options(joinedload(Sale.product)).limit(1)
    sale = await session.scalar(base.where(Sale.ends_at > utcnow()).order_by(Sale.starts_at))
    if sale is None:
        sale = await session.scalar(base.order_by(Sale.ends_at.desc()))
    return SaleInfo.from_model(sale) if sale else None


class SaleCache:
    """Tiny in-process TTL cache with single-flight loading.

    At 8:00 PM every replica sees thousands of concurrent requests for the
    same sale at once. Without single-flight, each would miss the cache
    simultaneously and stampede PostgreSQL; with it, one coroutine per key
    per process loads, the rest await the same result.
    """

    _MAX_ENTRIES = 256

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], ttl_seconds: float) -> None:
        self._sessionmaker = sessionmaker
        self._ttl = ttl_seconds
        self._entries: dict[object, tuple[float, SaleInfo | None]] = {}
        self._locks: dict[object, asyncio.Lock] = {}

    async def get(self, sale_id: int) -> SaleInfo | None:
        return await self._get(("id", sale_id), lambda s: load_sale(s, sale_id))

    async def current(self) -> SaleInfo | None:
        return await self._get("current", load_current_sale)

    def invalidate(self) -> None:
        self._entries.clear()

    async def _get(
        self, key: object, loader: Callable[[AsyncSession], Awaitable[SaleInfo | None]]
    ) -> SaleInfo | None:
        entry = self._entries.get(key)
        if entry and entry[0] > time.monotonic():
            return entry[1]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            entry = self._entries.get(key)
            if entry and entry[0] > time.monotonic():
                return entry[1]
            async with self._sessionmaker() as session:
                value = await loader(session)
            if len(self._entries) >= self._MAX_ENTRIES:
                self._entries.clear()
            self._entries[key] = (time.monotonic() + self._ttl, value)
            return value


# --- Redis priming ------------------------------------------------------------------
async def prime_sale(
    session: AsyncSession, gate: InventoryGate, sale_id: int, *, overwrite: bool = False
) -> bool:
    row = (
        await session.execute(
            select(Sale.starts_at, Sale.ends_at, Inventory.stock)
            .join(Inventory, Inventory.sale_id == Sale.id)
            .where(Sale.id == sale_id)
        )
    ).first()
    if row is None:
        return False
    return await gate.prime(
        sale_id, stock=row.stock, starts_at=row.starts_at, ends_at=row.ends_at, overwrite=overwrite
    )


async def prime_open_sales(
    sessionmaker: async_sessionmaker[AsyncSession], gate: InventoryGate
) -> None:
    """Startup self-heal: load tokens for every not-yet-ended sale (SET NX).

    Best effort: a replica must still boot if the database is briefly
    unreachable or not migrated yet (first deploy). Checkout re-primes on
    demand, so nothing is lost by skipping this.
    """
    try:
        async with sessionmaker() as session:
            sale_ids = (await session.scalars(select(Sale.id).where(Sale.ends_at > utcnow()))).all()
            for sale_id in sale_ids:
                if await prime_sale(session, gate, sale_id):
                    log.warning("primed redis inventory from database", extra={"sale_id": sale_id})
    except Exception:
        log.warning("startup priming skipped; will prime on demand", exc_info=True)


# --- Admin operations ---------------------------------------------------------------
async def reset_sale(
    session: AsyncSession,
    gate: InventoryGate,
    sale_id: int,
    *,
    stock: int,
    starts_in_seconds: int,
    duration_minutes: int,
) -> SaleInfo:
    sale = await session.get(Sale, sale_id)
    if sale is None:
        raise AppError(404, "SALE_NOT_FOUND", "Sale not found.")
    now = utcnow()
    sale.starts_at = now + timedelta(seconds=starts_in_seconds)
    sale.ends_at = sale.starts_at + timedelta(minutes=duration_minutes)
    sale.total_stock = stock
    await session.execute(delete(Order).where(Order.sale_id == sale_id))
    await session.execute(
        update(Inventory).where(Inventory.sale_id == sale_id).values(stock=stock, updated_at=now)
    )
    await session.commit()
    await gate.prime(
        sale_id, stock=stock, starts_at=sale.starts_at, ends_at=sale.ends_at, overwrite=True
    )
    info = await load_sale(session, sale_id)
    assert info is not None
    log.info(
        "sale reset", extra={"sale_id": sale_id, "stock": stock, "starts_at": str(info.starts_at)}
    )
    return info


async def sale_stats(
    session: AsyncSession, gate: InventoryGate, sale_id: int, *, queue_depth: int | None
) -> SaleStatsOut:
    def count(status: OrderStatus) -> Any:
        return func.count(Order.id).filter(Order.status == status)

    # ONE statement => one MVCC snapshot. Reading stock and the order counts
    # in separate queries would compare two different moments while workers
    # are committing, and report false inconsistencies.
    row = (
        await session.execute(
            select(
                Sale.total_stock,
                Inventory.stock,
                count(OrderStatus.CONFIRMED).label("confirmed"),
                count(OrderStatus.REJECTED_SOLD_OUT).label("rejected_sold_out"),
                count(OrderStatus.REJECTED_DUPLICATE).label("rejected_duplicate"),
                count(OrderStatus.FAILED).label("failed"),
            )
            .join(Inventory, Inventory.sale_id == Sale.id)
            .outerjoin(Order, Order.sale_id == Sale.id)
            .where(Sale.id == sale_id)
            .group_by(Sale.total_stock, Inventory.stock)
        )
    ).first()
    if row is None:
        raise AppError(404, "SALE_NOT_FOUND", "Sale not found.")
    confirmed = int(row.confirmed)
    return SaleStatsOut(
        sale_id=sale_id,
        total_stock=row.total_stock,
        db_stock=row.stock,
        redis_stock=await gate.remaining(sale_id),
        reservations=await gate.reservations(sale_id),
        confirmed=confirmed,
        rejected_sold_out=row.rejected_sold_out,
        rejected_duplicate=row.rejected_duplicate,
        failed=row.failed,
        queue_depth=queue_depth,
        oversold=confirmed > row.total_stock,
        # The invariant that must ALWAYS hold: every unit is either still in
        # stock or attached to exactly one confirmed order.
        consistent=confirmed + row.stock == row.total_stock,
    )


async def reconcile_sale(
    session: AsyncSession, gate: InventoryGate, sale_id: int, *, queue_depth: int | None
) -> tuple[int | None, int]:
    """Re-align the Redis token with PostgreSQL once the queue is drained.

    Redis can drift *below* the truth (e.g. an API crash between reserving
    and publishing leaks a token — undersell, never oversell). With nothing
    in flight, PostgreSQL's stock is exact, so copy it back.
    """
    if queue_depth is None or queue_depth > 0:
        raise AppError(409, "QUEUE_NOT_DRAINED", "Reconcile only once the order queue is empty.")
    stock = await session.scalar(select(Inventory.stock).where(Inventory.sale_id == sale_id))
    if stock is None:
        raise AppError(404, "SALE_NOT_FOUND", "Sale not found.")
    before = await gate.remaining(sale_id)
    await gate.set_stock(sale_id, stock)
    return before, stock


async def seed_demo_sale(
    session: AsyncSession, *, stock: int, starts_in_seconds: int, duration_minutes: int
) -> tuple[int, bool]:
    """Idempotently create the initial product and sale when none exists."""
    existing = await session.scalar(select(Sale.id).order_by(Sale.id).limit(1))
    if existing is not None:
        return existing, False
    product = Product(
        sku="NOVA-X-PRO-256",
        name="Nova X Pro 5G (256 GB)",
        description=(
            '6.7" 120 Hz AMOLED, 200 MP camera, 5000 mAh battery. '
            "Festival flash-sale price — limited to 500 units, one per customer."
        ),
        price_cents=4_999_900,
        currency="INR",
    )
    session.add(product)
    await session.flush()
    starts_at = utcnow() + timedelta(seconds=starts_in_seconds)
    sale = Sale(
        product_id=product.id,
        name="Festival Flash Sale",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=duration_minutes),
        total_stock=stock,
    )
    session.add(sale)
    await session.flush()
    session.add(Inventory(sale_id=sale.id, stock=stock))
    await session.commit()
    return sale.id, True
