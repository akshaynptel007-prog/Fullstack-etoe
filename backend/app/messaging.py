"""RabbitMQ topology and the reliable order publisher.

    checkout exchange ──order.reserved──► orders queue ──► worker
          ▲                                   │ (reject)
          │ TTL expires                        ▼
    orders.retry queue ◄── retry exchange    dlx ──► orders.dlq   (ops inspect/replay)

* Durable exchanges/queues + persistent messages survive a broker restart.
* Publisher confirms: the API only answers 202 once the broker has accepted
  responsibility for the message; `mandatory=True` turns "routed nowhere"
  into an error instead of a silent drop.
* Transient worker failures go through a TTL'd retry queue (delayed retry
  without a plugin); poison messages go to the DLQ, never loop forever.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from aio_pika.abc import (
    AbstractChannel,
    AbstractExchange,
    AbstractQueue,
    AbstractRobustConnection,
)

from app.config import Settings
from app.schemas import OrderReservedMessage

log = logging.getLogger(__name__)

ROUTING_KEY = "order.reserved"


@dataclass(frozen=True, slots=True)
class TopologyNames:
    exchange: str
    retry_exchange: str
    dead_letter_exchange: str
    queue: str
    retry_queue: str
    dead_letter_queue: str

    @classmethod
    def for_namespace(cls, ns: str) -> "TopologyNames":
        return cls(
            exchange=f"{ns}.checkout",
            retry_exchange=f"{ns}.checkout.retry",
            dead_letter_exchange=f"{ns}.checkout.dlx",
            queue=f"{ns}.orders",
            retry_queue=f"{ns}.orders.retry",
            dead_letter_queue=f"{ns}.orders.dlq",
        )


@dataclass(frozen=True, slots=True)
class Topology:
    names: TopologyNames
    exchange: AbstractExchange
    retry_exchange: AbstractExchange
    queue: AbstractQueue


async def connect_rabbitmq(settings: Settings, *, name: str) -> AbstractRobustConnection:
    """Connect with bounded exponential backoff (broker may still be booting)."""
    delay = 0.5
    for attempt in range(1, settings.rabbitmq_connect_attempts + 1):
        try:
            return await aio_pika.connect_robust(
                settings.rabbitmq_url,
                client_properties={"connection_name": name},
                timeout=10,
            )
        except (OSError, aio_pika.exceptions.AMQPError) as exc:
            if attempt == settings.rabbitmq_connect_attempts:
                raise
            log.warning(
                "rabbitmq not reachable, retrying",
                extra={"attempt": attempt, "error": repr(exc), "retry_in_s": delay},
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5.0)
    raise RuntimeError("unreachable")


async def declare_topology(channel: AbstractChannel, settings: Settings) -> Topology:
    names = TopologyNames.for_namespace(settings.rabbitmq_namespace)
    queue_type: dict[str, Any] = {"x-queue-type": settings.rabbitmq_queue_type}

    exchange = await channel.declare_exchange(names.exchange, ExchangeType.DIRECT, durable=True)
    retry_exchange = await channel.declare_exchange(
        names.retry_exchange, ExchangeType.DIRECT, durable=True
    )
    dlx = await channel.declare_exchange(
        names.dead_letter_exchange, ExchangeType.DIRECT, durable=True
    )

    queue = await channel.declare_queue(
        names.queue,
        durable=True,
        arguments={
            **queue_type,
            "x-dead-letter-exchange": names.dead_letter_exchange,
            "x-dead-letter-routing-key": ROUTING_KEY,
        },
    )
    await queue.bind(exchange, ROUTING_KEY)

    retry_queue = await channel.declare_queue(
        names.retry_queue,
        durable=True,
        arguments={
            **queue_type,
            "x-message-ttl": settings.worker_retry_delay_ms,
            "x-dead-letter-exchange": names.exchange,
            "x-dead-letter-routing-key": ROUTING_KEY,
        },
    )
    await retry_queue.bind(retry_exchange, ROUTING_KEY)

    dlq = await channel.declare_queue(names.dead_letter_queue, durable=True, arguments=queue_type)
    await dlq.bind(dlx, ROUTING_KEY)

    return Topology(names=names, exchange=exchange, retry_exchange=retry_exchange, queue=queue)


def build_order_message(payload: OrderReservedMessage, *, attempt: int = 0) -> Message:
    return Message(
        body=payload.model_dump_json().encode(),
        content_type="application/json",
        delivery_mode=DeliveryMode.PERSISTENT,
        message_id=str(payload.order_id),
        correlation_id=payload.request_id,
        type="order.reserved.v1",
        headers={"x-attempt": attempt},
    )


class OrderPublisher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._topology: Topology | None = None

    async def start(self) -> None:
        self._connection = await connect_rabbitmq(self._settings, name="flashsale-api")
        self._channel = await self._connection.channel(
            publisher_confirms=True, on_return_raises=True
        )
        self._topology = await declare_topology(self._channel, self._settings)

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and not self._connection.is_closed

    @property
    def topology(self) -> Topology:
        if self._topology is None:
            raise RuntimeError("publisher not started")
        return self._topology

    async def publish(self, payload: OrderReservedMessage) -> None:
        """Returns only after the broker confirmed the message (raises otherwise)."""
        await self.topology.exchange.publish(
            build_order_message(payload),
            routing_key=ROUTING_KEY,
            mandatory=True,
            timeout=self._settings.rabbitmq_publish_timeout_seconds,
        )

    async def queue_depth(self) -> int | None:
        """Ready messages in the main + retry queues (None if broker unreachable)."""
        if self._connection is None or self._connection.is_closed:
            return None
        try:
            # Separate short-lived channel: a failing passive declare closes
            # its channel, and that must never be the publishing channel.
            async with self._connection.channel() as channel:
                total = 0
                for name in (self.topology.names.queue, self.topology.names.retry_queue):
                    queue = await channel.declare_queue(name, passive=True)
                    total += queue.declaration_result.message_count or 0
                return total
        except aio_pika.exceptions.AMQPError:
            log.warning("could not read queue depth", exc_info=True)
            return None

    async def purge(self) -> None:
        if self._connection is None:
            return
        async with self._connection.channel() as channel:
            for name in (self.topology.names.queue, self.topology.names.retry_queue):
                queue = await channel.declare_queue(name, passive=True)
                await queue.purge()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
