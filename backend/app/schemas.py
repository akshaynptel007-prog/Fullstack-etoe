import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import OrderStatus

SaleState = Literal["upcoming", "live", "sold_out", "ended"]


# --- Errors ----------------------------------------------------------------------
class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


# --- Auth ------------------------------------------------------------------------
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def bcrypt_byte_limit(cls, value: str) -> str:
        if len(value.encode()) > 72:
            raise ValueError("password must be at most 72 bytes")
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int
    user: UserOut


# --- Sales -----------------------------------------------------------------------
class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    description: str
    price_cents: int
    currency: str


class SaleOut(BaseModel):
    id: int
    name: str
    starts_at: datetime
    ends_at: datetime
    total_stock: int
    product: ProductOut


class SaleStatusOut(BaseModel):
    sale_id: int
    state: SaleState
    remaining: int
    total_stock: int
    starts_at: datetime
    ends_at: datetime
    server_time_ms: int


class ServerTimeOut(BaseModel):
    server_time_ms: int


# --- Checkout / orders -----------------------------------------------------------
class CheckoutAccepted(BaseModel):
    order_id: uuid.UUID
    status: OrderStatus
    status_url: str
    poll_after_ms: int
    duplicate: bool = False


class OrderOut(BaseModel):
    order_id: uuid.UUID
    sale_id: int
    status: OrderStatus
    terminal: bool
    poll_after_ms: int | None = None
    amount_cents: int | None = None
    reserved_at: datetime | None = None
    processed_at: datetime | None = None


class OrderListItem(BaseModel):
    order_id: uuid.UUID
    status: OrderStatus
    amount_cents: int
    currency: str
    sale_id: int
    sale_name: str
    product_name: str
    reserved_at: datetime
    processed_at: datetime


# --- Admin -----------------------------------------------------------------------
class ResetSaleIn(BaseModel):
    stock: int = Field(default=500, ge=0, le=1_000_000)
    starts_in_seconds: int = Field(default=30, ge=0, le=7 * 24 * 3600)
    duration_minutes: int = Field(default=60, ge=1, le=7 * 24 * 60)


class SaleStatsOut(BaseModel):
    sale_id: int
    total_stock: int
    db_stock: int
    redis_stock: int | None
    reservations: int
    confirmed: int
    rejected_sold_out: int
    rejected_duplicate: int
    failed: int
    queue_depth: int | None
    oversold: bool
    consistent: bool


class ReconcileOut(BaseModel):
    sale_id: int
    redis_stock_before: int | None
    redis_stock_after: int


# --- Queue message -----------------------------------------------------------------
class OrderReservedMessage(BaseModel):
    """Contract between the API (producer) and the order worker (consumer)."""

    schema_version: Literal[1] = 1
    order_id: uuid.UUID
    sale_id: int
    user_id: uuid.UUID
    amount_cents: int
    reserved_at: datetime
    request_id: str | None = None
