from datetime import UTC, datetime, timedelta

import pytest

from app.schemas import ProductOut
from app.services.sales import SaleInfo, compute_state

NOW = datetime(2026, 10, 27, 20, 0, tzinfo=UTC)
SALE = SaleInfo(
    id=1,
    name="t",
    starts_at=NOW,
    ends_at=NOW + timedelta(hours=1),
    total_stock=500,
    product=ProductOut(id=1, sku="s", name="p", description="", price_cents=1, currency="INR"),
)


@pytest.mark.parametrize(
    ("now", "remaining", "state"),
    [
        (NOW - timedelta(seconds=1), 500, "upcoming"),
        (NOW, 500, "live"),
        (NOW + timedelta(minutes=1), 0, "sold_out"),
        (NOW - timedelta(minutes=1), 0, "sold_out"),
        (NOW + timedelta(hours=1), 10, "ended"),
    ],
)
def test_compute_state(now: datetime, remaining: int, state: str) -> None:
    assert compute_state(SALE, remaining, now) == state
