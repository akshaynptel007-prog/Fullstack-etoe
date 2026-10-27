# ADR-0001: Redis Lua gate in front of a conditional database update

- **Status:** accepted
- **Context:** 500 units, ~100k checkout attempts in 10 s. Trial runs oversold (540/500), timed out
  on row locks, and timed out at the API.

## Decision

1. **Admission control in Redis.** A Lua script atomically checks the sale window (using Redis'
   clock), de-duplicates the user, checks `stock > 0` and decrements. Only admitted requests (≤ stock)
   proceed.
2. **Durable hand-off through RabbitMQ.** The API answers `202 Accepted` with a tracking URL once the
   broker confirms the message.
3. **Authoritative guard in PostgreSQL.** Workers persist each order in a transaction:
   idempotent insert, then `UPDATE … SET stock = stock - 1 WHERE … AND stock > 0`.
4. **Constraints as a backstop.** `CHECK (stock >= 0)`, and a partial unique index on confirmed
   orders per user.

## Alternatives considered

| Option | Why not |
|---|---|
| DB only, `SELECT … FOR UPDATE` | correct but serialises 100k transactions on one row: lock timeouts, pool exhaustion |
| DB only, optimistic version check | correct, but O(N²) retries under extreme contention |
| DB only, conditional UPDATE in the request | correct, but 100k transactions still hit one row and one connection pool |
| Redis `DECR` alone (no DB guard) | fast, but a Redis failover/flush could over-admit with nothing to catch it |
| Redis `WATCH`/`MULTI` | optimistic: aborts and retries under contention |
| Partitioned stock (N sub-counters) | spreads contention, but complicates "exactly 500" and the sold-out state; unnecessary at ~100k ops/s |

## Consequences

- PostgreSQL sees ≈ stock writes, not traffic-sized load.
- Two sources of stock exist. Redis is a cache with admission semantics, PostgreSQL is the truth.
  Drift is only ever in the safe direction (undersell) except after Redis data loss, which the DB
  guard handles. `reconcile` re-aligns them when the queue is empty.
- The user sees "reserved" before "confirmed". The UI is honest about that two-step state.
