"""Per-process fan-out of live stock to SSE subscribers.

One background task per API process reads the Redis counters every
`interval` and pushes changes to in-memory queues. Redis load is therefore
O(processes), not O(connected browsers): 50k open streams across 10
replicas cost 20 Redis reads per second, total.
"""

import asyncio
import contextlib
import logging
from collections import defaultdict

from app.metrics import SSE_CONNECTIONS, STOCK_REMAINING
from app.services.inventory import InventoryGate

log = logging.getLogger(__name__)

_UNSET = object()


def _offer(queue: "asyncio.Queue[int | None]", value: int | None) -> None:
    # Subscribers only care about the latest value: drop a stale one if the
    # client is slow rather than letting a backlog grow.
    if queue.full():
        with contextlib.suppress(asyncio.QueueEmpty):
            queue.get_nowait()
    queue.put_nowait(value)


class SaleBroadcaster:
    def __init__(self, gate: InventoryGate, *, interval_seconds: float) -> None:
        self._gate = gate
        self._interval = interval_seconds
        self._subscribers: dict[int, set[asyncio.Queue[int | None]]] = defaultdict(set)
        self._last: dict[int, object] = {}
        self._task: asyncio.Task[None] | None = None

    @property
    def connection_count(self) -> int:
        return sum(len(s) for s in self._subscribers.values())

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="sale-broadcaster")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def subscribe(self, sale_id: int) -> "asyncio.Queue[int | None]":
        queue: asyncio.Queue[int | None] = asyncio.Queue(maxsize=1)
        self._subscribers[sale_id].add(queue)
        SSE_CONNECTIONS.inc()
        return queue

    def unsubscribe(self, sale_id: int, queue: "asyncio.Queue[int | None]") -> None:
        subs = self._subscribers.get(sale_id)
        if subs and queue in subs:
            subs.discard(queue)
            SSE_CONNECTIONS.dec()
            if not subs:
                del self._subscribers[sale_id]
                self._last.pop(sale_id, None)

    async def _run(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("broadcaster tick failed", exc_info=True)
            await asyncio.sleep(self._interval)

    async def _tick(self) -> None:
        sale_ids = list(self._subscribers)
        if not sale_ids:
            return
        for sale_id, remaining in (await self._gate.remaining_many(sale_ids)).items():
            if remaining is not None:
                STOCK_REMAINING.labels(str(sale_id)).set(remaining)
            if self._last.get(sale_id, _UNSET) == remaining:
                continue
            self._last[sale_id] = remaining
            for queue in list(self._subscribers.get(sale_id, ())):
                _offer(queue, remaining)
