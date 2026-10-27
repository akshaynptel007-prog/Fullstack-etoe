# ADR-0003: Server-Sent Events with an adaptive polling fallback

- **Status:** accepted

## Context

During the sale every open page wants the live "units left" counter, and each buyer wants their order
status. 100k clients may be connected at 8:00 PM.

## Options

| | Short polling | Long polling | **SSE** | WebSockets |
|---|---|---|---|---|
| Direction needed | server → client | server → client | **server → client** | bidirectional (unused) |
| Works through CDN / ALB / proxies | yes | mostly | **yes (plain HTTP)** | needs upgrade support everywhere |
| Reconnect / resume | manual | manual | **built into `EventSource`** | manual |
| Server cost per client | a request per interval | a held request | **a held response + tiny queue** | a held socket + framing |
| Cacheable at the edge | **yes** | no | no | no |

## Decision

- **Countdown:** no network at all. NTP-style clock offset, rendered locally.
- **Live stock:** SSE (`/sales/{id}/events`). One broadcaster task per API process reads Redis every
  500 ms and fans out to in-memory queues, so Redis load is O(processes), not O(clients). Heartbeats
  every 15 s keep ALB/CloudFront/NGINX idle timers from closing streams. The stream ends itself when
  the sale is sold out or over.
- **Fallback:** adaptive polling of `/sales/{id}/status`, which is **edge-cached for 1 s with request
  collapsing**. 100k pollers cost about one origin request per second per edge. The interval adapts
  to the sale phase, has jitter, and pauses in hidden tabs. The server can shed SSE (503 above
  `SSE_MAX_CONNECTIONS_PER_PROCESS`) to force clients onto the cached path.
- **Order status:** short polling of the `202` tracking URL with exponential backoff and jitter. The
  order is pending for about a second; a persistent channel per buyer is not worth it.

## Consequences

- Each SSE stream holds a connection. Capacity planning counts streams per task (default cap 5,000 per
  process), and the cached polling path absorbs any overflow.
- No WebSocket infrastructure (sticky sessions, upgrade handling) is needed anywhere.
