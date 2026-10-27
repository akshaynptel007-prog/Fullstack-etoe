import time
import uuid

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.deps import ResourcesDep, SessionDep, UserIdDep
from app.errors import AppError
from app.models import Order, OrderStatus, Product, Sale
from app.schemas import OrderListItem, OrderOut

router = APIRouter(prefix="/orders", tags=["orders"])

# A PENDING status older than this is double-checked against PostgreSQL, in
# case the worker committed but could not update Redis.
_STALE_PENDING_MS = 10_000


@router.get("/{order_id}", summary="Order tracking URL returned by checkout (poll this)")
async def get_order(
    order_id: uuid.UUID,
    user_id: UserIdDep,
    resources: ResourcesDep,
    session: SessionDep,
    response: Response,
) -> OrderOut:
    response.headers["Cache-Control"] = "no-store"
    poll_after = resources.settings.order_poll_after_ms

    cached = await resources.order_status.get(order_id)
    if cached is not None and cached.user_id != user_id:
        raise AppError(404, "ORDER_NOT_FOUND", "Order not found.")
    fresh = cached is not None and (
        cached.status.is_terminal or time.time() * 1000 - cached.updated_at_ms < _STALE_PENDING_MS
    )
    if cached is not None and fresh:
        return OrderOut(
            order_id=order_id,
            sale_id=cached.sale_id,
            status=cached.status,
            terminal=cached.status.is_terminal,
            poll_after_ms=None if cached.status.is_terminal else poll_after,
        )

    order = await session.get(Order, order_id)
    if order is None or order.user_id != user_id:
        if cached is not None:  # still queued: keep the client polling
            return OrderOut(
                order_id=order_id,
                sale_id=cached.sale_id,
                status=OrderStatus.PENDING,
                terminal=False,
                poll_after_ms=poll_after,
            )
        raise AppError(404, "ORDER_NOT_FOUND", "Order not found.")
    return OrderOut(
        order_id=order.id,
        sale_id=order.sale_id,
        status=order.status,
        terminal=True,
        amount_cents=order.amount_cents,
        reserved_at=order.reserved_at,
        processed_at=order.processed_at,
    )


@router.get("", summary="The signed-in user's orders")
async def list_orders(user_id: UserIdDep, session: SessionDep) -> list[OrderListItem]:
    # One query with explicit joins. The ORM relationships are lazy="raise",
    # so an accidental per-row lazy load (the N+1 pattern) fails loudly in
    # tests instead of silently issuing one query per order.
    rows = await session.execute(
        select(
            Order.id,
            Order.status,
            Order.amount_cents,
            Order.reserved_at,
            Order.processed_at,
            Sale.id.label("sale_id"),
            Sale.name.label("sale_name"),
            Product.name.label("product_name"),
            Product.currency,
        )
        .join(Sale, Sale.id == Order.sale_id)
        .join(Product, Product.id == Sale.product_id)
        .where(Order.user_id == user_id)
        .order_by(Order.reserved_at.desc())
        .limit(50)
    )
    return [
        OrderListItem(
            order_id=r.id,
            status=r.status,
            amount_cents=r.amount_cents,
            currency=r.currency,
            sale_id=r.sale_id,
            sale_name=r.sale_name,
            product_name=r.product_name,
            reserved_at=r.reserved_at,
            processed_at=r.processed_at,
        )
        for r in rows
    ]
