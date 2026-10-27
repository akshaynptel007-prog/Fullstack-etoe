"""Integration fixtures: real PostgreSQL, Redis and RabbitMQ.

Safety: whatever DATABASE_URL / REDIS_URL point at, tests force a `*_test`
database, Redis logical DB 15 and a separate RabbitMQ namespace, so running
the suite can never wipe the development stack's data.
"""

import asyncio
import contextlib
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from aio_pika.abc import AbstractRobustConnection
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import create_engine, create_sessionmaker
from app.main import create_app
from app.messaging import connect_rabbitmq, declare_topology
from app.models import Inventory, Product, Sale, User
from app.redis_client import create_redis
from app.security import create_access_token, hash_password
from app.services.inventory import InventoryGate
from app.services.order_status import OrderStatusStore
from app.services.sales import SaleInfo, load_sale, prime_sale, utcnow
from app.worker.processor import OrderProcessor

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _test_settings() -> Settings:
    base = Settings(_env_file=None)
    db_url = make_url(base.database_url)
    db_name = db_url.database or "flashsale"
    if not db_name.endswith("_test"):
        db_name = f"{db_name}_test"
    redis = urlsplit(base.redis_url)
    return base.model_copy(
        update={
            "app_env": "test",
            "database_url": db_url.set(database=db_name).render_as_string(hide_password=False),
            "redis_url": urlunsplit(redis._replace(path="/15")),
            "rabbitmq_namespace": "flashsale-test",
            "bcrypt_rounds": 4,
            "worker_retry_delay_ms": 200,
            "rate_limit_checkout_per_ip": 100_000,
            "db_pool_size": 20,
            "db_max_overflow": 20,
        }
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    return _test_settings()


@pytest.fixture(scope="session", autouse=True)
async def _database(settings: Settings) -> None:
    url = make_url(settings.database_url)
    admin_dsn = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", url.database)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await conn.close()
    # Run the real migrations — the schema under test is the one we ship.
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": settings.database_url},
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
async def engine(settings: Settings, _database: None) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings, application_name="flashsale-tests")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture(scope="session")
async def redis(settings: Settings) -> AsyncIterator[Redis]:
    client = create_redis(settings)
    yield client
    await client.aclose()


@pytest.fixture(scope="session")
async def mq(settings: Settings) -> AsyncIterator[AbstractRobustConnection]:
    connection = await connect_rabbitmq(settings, name="flashsale-tests")
    yield connection
    await connection.close()


@pytest.fixture(autouse=True)
async def _clean(
    engine: AsyncEngine, redis: Redis, mq: AbstractRobustConnection, settings: Settings
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE orders, inventory, sales, products, users RESTART IDENTITY CASCADE")
        )
    await redis.flushdb()
    async with mq.channel() as channel:
        topology = await declare_topology(channel, settings)
        for name in (
            topology.names.queue,
            topology.names.retry_queue,
            topology.names.dead_letter_queue,
        ):
            queue = await channel.declare_queue(name, passive=True)
            await queue.purge()


@pytest.fixture
def gate(redis: Redis) -> InventoryGate:
    return InventoryGate(redis)


SaleFactory = Callable[..., Any]


@pytest.fixture
def make_sale(sessionmaker: async_sessionmaker[AsyncSession], gate: InventoryGate) -> SaleFactory:
    async def factory(
        *, stock: int = 10, starts_in: float = -1, duration_minutes: int = 60, prime: bool = True
    ) -> SaleInfo:
        async with sessionmaker() as session:
            product = Product(
                sku=f"SKU-{uuid.uuid4().hex[:8]}",
                name="Test Phone",
                description="",
                price_cents=1000,
                currency="INR",
            )
            session.add(product)
            await session.flush()
            starts_at = utcnow() + timedelta(seconds=starts_in)
            sale = Sale(
                product_id=product.id,
                name="Test Sale",
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=duration_minutes),
                total_stock=stock,
            )
            session.add(sale)
            await session.flush()
            session.add(Inventory(sale_id=sale.id, stock=stock))
            await session.commit()
            if prime:
                await prime_sale(session, gate, sale.id)
            info = await load_sale(session, sale.id)
            assert info is not None
            return info

    return factory


@dataclass(frozen=True)
class AuthedUser:
    id: uuid.UUID
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


_FIXED_HASH = hash_password("password123", rounds=4)


@pytest.fixture
def make_users(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> Callable[[int], Any]:
    async def factory(count: int) -> list[AuthedUser]:
        rows = [
            {
                "id": uuid.uuid4(),
                "email": f"u-{uuid.uuid4().hex}@example.com",
                "password_hash": _FIXED_HASH,
            }
            for _ in range(count)
        ]
        async with sessionmaker() as session:
            await session.execute(insert(User).values(rows))
            await session.commit()
        return [AuthedUser(r["id"], create_access_token(r["id"], settings)[0]) for r in rows]

    return factory


@pytest.fixture
async def worker(
    settings: Settings,
    mq: AbstractRobustConnection,
    sessionmaker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> AsyncIterator[None]:
    """An in-process order worker consuming the test namespace's queue."""
    channel = await mq.channel(publisher_confirms=True)
    await channel.set_qos(prefetch_count=settings.worker_prefetch)
    topology = await declare_topology(channel, settings)
    processor = OrderProcessor(
        settings=settings,
        sessionmaker=sessionmaker,
        gate=InventoryGate(redis),
        order_status=OrderStatusStore(redis, ttl_seconds=60),
        retry_exchange=topology.retry_exchange,
    )
    tag = await topology.queue.consume(processor.handle)
    yield
    await topology.queue.cancel(tag)
    with contextlib.suppress(Exception):
        await channel.close()


ClientFactory = Callable[..., contextlib.AbstractAsyncContextManager[AsyncClient]]


@pytest.fixture
def make_client(settings: Settings) -> ClientFactory:
    @contextlib.asynccontextmanager
    async def factory(**overrides: Any) -> AsyncIterator[AsyncClient]:
        app = create_app(settings.model_copy(update=overrides))
        async with LifespanManager(app) as manager:
            transport = ASGITransport(app=manager.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client

    return factory


@pytest.fixture
async def client(make_client: ClientFactory) -> AsyncIterator[AsyncClient]:
    async with make_client() as c:
        yield c
