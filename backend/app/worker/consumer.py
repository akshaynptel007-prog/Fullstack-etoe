import asyncio
import contextlib
import logging
import signal

from aio_pika.abc import AbstractIncomingMessage
from prometheus_client import start_http_server

from app.config import Settings
from app.db import create_engine, create_sessionmaker
from app.logging import configure_logging
from app.messaging import connect_rabbitmq, declare_topology
from app.redis_client import create_redis
from app.services.inventory import InventoryGate
from app.services.order_status import OrderStatusStore
from app.worker.processor import OrderProcessor

log = logging.getLogger(__name__)


class InflightTracker:
    """Counts messages being processed so shutdown can wait for them."""

    def __init__(self) -> None:
        self._count = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def enter(self) -> None:
        self._count += 1
        self._idle.clear()

    def leave(self) -> None:
        self._count -= 1
        if self._count == 0:
            self._idle.set()

    async def wait_idle(self, grace_seconds: float) -> bool:
        try:
            async with asyncio.timeout(grace_seconds):
                await self._idle.wait()
            return True
        except TimeoutError:
            return False


async def run_worker(settings: Settings) -> None:
    configure_logging(settings.log_level, service="worker")
    start_http_server(settings.worker_metrics_port)

    engine = create_engine(settings, application_name="flashsale-worker")
    sessionmaker = create_sessionmaker(engine)
    redis = create_redis(settings)
    connection = await connect_rabbitmq(settings, name="flashsale-worker")

    channel = await connection.channel(publisher_confirms=True)
    # prefetch bounds concurrency per worker (and DB connections in use).
    # WORKER_PREFETCH=1 gives strictly sequential, one-at-a-time consumption.
    await channel.set_qos(prefetch_count=settings.worker_prefetch)
    topology = await declare_topology(channel, settings)

    processor = OrderProcessor(
        settings=settings,
        sessionmaker=sessionmaker,
        gate=InventoryGate(redis),
        order_status=OrderStatusStore(redis, ttl_seconds=settings.order_status_ttl_seconds),
        retry_exchange=topology.retry_exchange,
    )
    inflight = InflightTracker()

    async def on_message(message: AbstractIncomingMessage) -> None:
        inflight.enter()
        try:
            await processor.handle(message)
        finally:
            inflight.leave()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    consumer_tag = await topology.queue.consume(on_message)
    log.info(
        "worker consuming",
        extra={"queue": topology.names.queue, "prefetch": settings.worker_prefetch},
    )

    await stop.wait()
    log.info("shutdown requested, draining in-flight messages")
    # Stop receiving new deliveries, finish (and ack) what we hold, then close.
    # Anything unacked at close is redelivered to another worker.
    await topology.queue.cancel(consumer_tag)
    drained = await inflight.wait_idle(settings.worker_shutdown_grace_seconds)
    if not drained:
        log.warning("grace period elapsed with messages in flight; they will be redelivered")
    with contextlib.suppress(Exception):
        await connection.close()
    await redis.aclose()
    await engine.dispose()
    log.info("worker stopped")
