"""initial schema: users, products, sales, inventory, orders

Revision ID: 0001
Revises:
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORDER_STATUSES = ("CONFIRMED", "REJECTED_SOLD_OUT", "REJECTED_DUPLICATE", "FAILED", "PENDING")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sku", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.CheckConstraint("price_cents >= 0", name="ck_products_price_non_negative"),
    )

    op.create_table(
        "sales",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_stock", sa.Integer, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_sales_window"),
        sa.CheckConstraint("total_stock >= 0", name="ck_sales_total_stock_non_negative"),
    )
    op.create_index("ix_sales_ends_at", "sales", ["ends_at"])

    # The single hot row per sale. CHECK (stock >= 0) is the last-resort
    # guard: even a buggy code path cannot commit a negative stock.
    op.create_table(
        "inventory",
        sa.Column(
            "sale_id",
            sa.Integer,
            sa.ForeignKey("sales.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("stock", sa.Integer, nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("stock >= 0", name="ck_inventory_stock_non_negative"),
    )

    order_status = postgresql.ENUM(*ORDER_STATUSES, name="order_status", create_type=False)
    order_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "sale_id", sa.Integer, sa.ForeignKey("sales.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", order_status, nullable=False),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("request_id", sa.String(64), nullable=True),
    )
    # One successful purchase per user per sale — enforced by the database,
    # independent of the Redis buyer set.
    op.create_index(
        "uq_orders_one_confirmed_per_user",
        "orders",
        ["sale_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'CONFIRMED'"),
    )
    op.create_index("ix_orders_user_reserved_at", "orders", ["user_id", "reserved_at"])
    op.create_index("ix_orders_sale_status", "orders", ["sale_id", "status"])


def downgrade() -> None:
    op.drop_table("orders")
    postgresql.ENUM(name="order_status").drop(op.get_bind(), checkfirst=True)
    op.drop_table("inventory")
    op.drop_index("ix_sales_ends_at", table_name="sales")
    op.drop_table("sales")
    op.drop_table("products")
    op.drop_table("users")
