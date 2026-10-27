import asyncio
import uuid

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.messaging import OrderPublisher
from app.models import OrderStatus
from app.services.inventory import InventoryGate
from tests.integration.conftest import AuthedUser, ClientFactory, SaleFactory


@pytest.fixture
def admin(settings: Settings) -> dict[str, str]:
    return {"X-Admin-Key": settings.admin_api_key.get_secret_value()}


async def _wait_for_terminal(client: AsyncClient, user: AuthedUser, order_id: str) -> dict:
    for _ in range(100):
        body = (await client.get(f"/api/v1/orders/{order_id}", headers=user.headers)).json()
        if body["terminal"]:
            return body
        await asyncio.sleep(0.05)
    pytest.fail(f"order {order_id} never reached a terminal state")


# --- Auth ------------------------------------------------------------------------
async def test_register_login_me(client: AsyncClient) -> None:
    creds = {"email": "Asha@Example.com", "password": "s3cret-pass"}
    created = await client.post("/api/v1/auth/register", json=creds)
    assert created.status_code == 201
    assert created.json()["user"]["email"] == "asha@example.com"

    dup = await client.post("/api/v1/auth/register", json=creds)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "EMAIL_TAKEN"

    bad = await client.post("/api/v1/auth/login", json={**creds, "password": "wrong-pass"})
    assert bad.status_code == 401

    login = await client.post("/api/v1/auth/login", json=creds)
    token = login.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == "asha@example.com"


# --- Checkout flow ---------------------------------------------------------------
async def test_checkout_requires_auth(client: AsyncClient, make_sale: SaleFactory) -> None:
    sale = await make_sale()
    response = await client.post(f"/api/v1/sales/{sale.id}/checkout")
    assert response.status_code == 401


async def test_checkout_before_start_is_rejected(
    client: AsyncClient, make_sale: SaleFactory, make_users
) -> None:
    sale = await make_sale(starts_in=3600)
    [user] = await make_users(1)
    response = await client.post(f"/api/v1/sales/{sale.id}/checkout", headers=user.headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SALE_NOT_STARTED"


async def test_checkout_accepts_then_confirms_asynchronously(
    client: AsyncClient, worker: None, make_sale: SaleFactory, make_users
) -> None:
    sale = await make_sale(stock=5)
    [user] = await make_users(1)

    response = await client.post(f"/api/v1/sales/{sale.id}/checkout", headers=user.headers)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "PENDING"
    assert response.headers["location"] == body["status_url"]
    assert response.headers["x-request-id"]

    final = await _wait_for_terminal(client, user, body["order_id"])
    assert final["status"] == OrderStatus.CONFIRMED

    # Clicking again is idempotent: same order, no second unit.
    again = await client.post(f"/api/v1/sales/{sale.id}/checkout", headers=user.headers)
    assert again.status_code == 200
    assert again.json()["order_id"] == body["order_id"]
    assert again.json()["duplicate"] is True

    orders = (await client.get("/api/v1/orders", headers=user.headers)).json()
    assert [o["order_id"] for o in orders] == [body["order_id"]]
    assert orders[0]["product_name"] == "Test Phone"


async def test_sold_out_returns_409(
    client: AsyncClient, make_sale: SaleFactory, make_users
) -> None:
    sale = await make_sale(stock=1)
    first, second = await make_users(2)
    assert (
        await client.post(f"/api/v1/sales/{sale.id}/checkout", headers=first.headers)
    ).status_code == 202
    response = await client.post(f"/api/v1/sales/{sale.id}/checkout", headers=second.headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SOLD_OUT"


async def test_orders_are_private(client: AsyncClient, make_sale: SaleFactory, make_users) -> None:
    sale = await make_sale(stock=5)
    owner, stranger = await make_users(2)
    order_id = (
        await client.post(f"/api/v1/sales/{sale.id}/checkout", headers=owner.headers)
    ).json()["order_id"]
    response = await client.get(f"/api/v1/orders/{order_id}", headers=stranger.headers)
    assert response.status_code == 404
    missing = await client.get(f"/api/v1/orders/{uuid.uuid4()}", headers=owner.headers)
    assert missing.status_code == 404


async def test_per_user_rate_limit(
    make_client: ClientFactory, make_sale: SaleFactory, make_users
) -> None:
    sale = await make_sale(starts_in=3600)
    [user] = await make_users(1)
    async with make_client(rate_limit_checkout_per_user=2) as client:
        codes = [
            (await client.post(f"/api/v1/sales/{sale.id}/checkout", headers=user.headers))
            for _ in range(3)
        ]
    assert [c.status_code for c in codes] == [409, 409, 429]
    assert int(codes[2].headers["retry-after"]) >= 1
    assert codes[2].json()["error"]["code"] == "RATE_LIMITED"


async def test_self_heals_when_redis_lost_the_token(
    client: AsyncClient, make_sale: SaleFactory, make_users, redis
) -> None:
    sale = await make_sale(stock=3)
    [user] = await make_users(1)
    await redis.flushdb()  # simulate a Redis restart without persistence
    response = await client.post(f"/api/v1/sales/{sale.id}/checkout", headers=user.headers)
    assert response.status_code == 202


# --- Sale status -------------------------------------------------------------------
async def test_status_is_edge_cacheable(client: AsyncClient, make_sale: SaleFactory) -> None:
    sale = await make_sale(stock=7)
    response = await client.get(f"/api/v1/sales/{sale.id}/status")
    assert response.status_code == 200
    assert response.json()["remaining"] == 7
    assert response.json()["state"] == "live"
    assert "max-age=1" in response.headers["cache-control"]

    current = (await client.get("/api/v1/sales/current")).json()
    assert current["id"] == sale.id


async def test_sse_stream_reports_status_and_ends_when_sold_out(
    client: AsyncClient, make_sale: SaleFactory
) -> None:
    sale = await make_sale(stock=0)
    response = await client.get(f"/api/v1/sales/{sale.id}/events")
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: status" in response.text
    assert '"state":"sold_out"' in response.text
    assert "event: end" in response.text


# --- Admin -------------------------------------------------------------------------
async def test_admin_requires_key(client: AsyncClient, make_sale: SaleFactory) -> None:
    sale = await make_sale()
    response = await client.get(f"/api/v1/admin/sales/{sale.id}/stats")
    assert response.status_code == 401
    wrong = await client.get(f"/api/v1/admin/sales/{sale.id}/stats", headers={"X-Admin-Key": "x"})
    assert wrong.status_code == 401


async def test_admin_reset_restocks(
    client: AsyncClient, make_sale: SaleFactory, admin: dict[str, str]
) -> None:
    sale = await make_sale(stock=1)
    response = await client.post(
        f"/api/v1/admin/sales/{sale.id}/reset",
        json={"stock": 42, "starts_in_seconds": 0, "duration_minutes": 5},
        headers=admin,
    )
    assert response.status_code == 200
    stats = (await client.get(f"/api/v1/admin/sales/{sale.id}/stats", headers=admin)).json()
    assert stats["redis_stock"] == 42
    assert stats["db_stock"] == 42
    assert stats["consistent"] is True


# --- The headline guarantee ---------------------------------------------------------
async def test_burst_of_concurrent_checkouts_never_oversells(
    client: AsyncClient, worker: None, make_sale: SaleFactory, make_users, admin: dict[str, str]
) -> None:
    """2,000 buyers race for 500 units through the real HTTP + queue + DB path."""
    stock, buyers = 500, 2000
    sale = await make_sale(stock=stock)
    users = await make_users(buyers)

    responses = await asyncio.gather(
        *(client.post(f"/api/v1/sales/{sale.id}/checkout", headers=u.headers) for u in users)
    )
    codes = [r.status_code for r in responses]
    assert codes.count(202) == stock
    assert codes.count(409) == buyers - stock
    assert all(r.json()["error"]["code"] == "SOLD_OUT" for r in responses if r.status_code == 409)

    stats: dict = {}
    for _ in range(200):
        stats = (await client.get(f"/api/v1/admin/sales/{sale.id}/stats", headers=admin)).json()
        if stats["confirmed"] + stats["rejected_sold_out"] >= stock:
            break
        await asyncio.sleep(0.1)

    assert stats["confirmed"] == stock
    assert stats["db_stock"] == 0
    assert stats["redis_stock"] == 0
    assert stats["oversold"] is False
    assert stats["consistent"] is True


async def test_broker_failure_releases_the_unit(
    client: AsyncClient,
    make_sale: SaleFactory,
    make_users,
    gate: InventoryGate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If RabbitMQ does not confirm, the reservation is undone and the client told to retry."""
    sale = await make_sale(stock=1)
    [user] = await make_users(1)

    async def broken_publish(self: OrderPublisher, payload: object) -> None:
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(OrderPublisher, "publish", broken_publish)
    response = await client.post(f"/api/v1/sales/{sale.id}/checkout", headers=user.headers)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "2"
    assert response.json()["error"]["code"] == "QUEUE_UNAVAILABLE"
    assert await gate.remaining(sale.id) == 1  # the unit is back on sale
    assert await gate.reservations(sale.id) == 0
