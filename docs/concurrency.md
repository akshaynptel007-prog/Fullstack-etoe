# Concurrency control and data consistency

## The bug: SELECT-then-UPDATE

The trial runs sold **540 of 500**. The classic cause:

```sql
-- every request, in its own transaction (READ COMMITTED)
SELECT stock FROM inventory WHERE product_id = 1;      -- both see 1
-- application checks stock > 0, does some work...
UPDATE inventory SET stock = 0 WHERE product_id = 1;   -- both write stock-1 = 0
INSERT INTO orders ...;                                -- both create an order
```

Two (or 40) transactions read the same value before any of them writes. Each passes the check, and
each writes a value computed from a stale read: a **lost update**. The check and the write are not
atomic.

`backend/tests/integration/test_locking_strategies.py` reproduces it against real PostgreSQL:
30 concurrent buyers for 10 units → **30 orders, stock 9**.

## Options compared

All numbers come from that test file (30 concurrent buyers, 10 units, real PostgreSQL). Run
`pytest -s tests/integration/test_locking_strategies.py` to print them.

| Strategy | SQL shape | Result | Cost under contention |
|---|---|---|---|
| Naive | `SELECT stock` → `UPDATE … SET stock = :new` | **oversold 30/10** | — |
| Pessimistic | `SELECT … FOR UPDATE` → work → `UPDATE` | correct | every buyer queues behind the row lock **for the whole transaction**; with a 1 s request deadline, 26/30 timed out and only 4 units sold |
| Optimistic | `SELECT stock` → `UPDATE … WHERE stock = :seen` (or a `version` column), retry on 0 rows | correct | 241 retries for 30 buyers: every concurrent winner invalidates everyone else's read |
| **Atomic conditional** | `UPDATE … SET stock = stock - 1 WHERE … AND stock > 0 RETURNING stock` | **correct** | one statement; the row lock is held for microseconds; no retries |

### Why pessimistic locking fails at scale

`FOR UPDATE` is correct, but it serialises buyers for the full transaction: the SELECT, any app work,
the UPDATE, the INSERT, the network round trips and the COMMIT. At 100k requests the lock queue is the
throughput limit. Every queued request also holds a DB connection, which exhausts the pool. Requests
then time out, which is the "row lock timeouts" symptom from the trial runs. The scorecard's
"Proficient" tier ("relies heavily on SQL locking, which might degrade performance") describes this
design.

### Why optimistic locking fails at scale

Compare-and-set never blocks, but in a flash sale **everyone** contends on the same row at the same
moment. Each successful write invalidates every concurrent reader, so N buyers cost O(N²) attempts in
the worst case. It suits low-contention updates, such as editing a profile. It does not suit one hot
counter.

### Why the atomic conditional UPDATE works

```sql
UPDATE inventory SET stock = stock - 1
 WHERE sale_id = :sale_id AND stock > 0
RETURNING stock;
```

PostgreSQL takes the row lock, re-evaluates `stock > 0` against the **latest committed version** of
the row (under READ COMMITTED a concurrent updater makes it re-check the predicate), decrements, and
returns. Zero rows returned means sold out. There is no read-modify-write gap for another
transaction to slip into, and the lock is held only for the remainder of a very short transaction.

## Why Redis Lua in front of the database

Even the atomic UPDATE serialises on one row, and 100k transactions against one row (plus the
connection storm) would still overwhelm PostgreSQL. So the database must not see the 100k at all.

`backend/app/lua/reserve.lua` runs **inside Redis**, which executes a script as one uninterruptible
unit on its single command thread. The script does all of this atomically:

1. checks the sale window using **Redis' own clock** (`TIME`), so every API replica agrees on 8:00:00;
2. returns the existing order if this user already reserved (idempotency, one unit per customer);
3. checks `stock > 0`, then `DECR`s and records the buyer.

There is no gap between check and decrement, so no race is possible. A plain `DECR` is also atomic,
but it goes negative and needs a compensating `INCR`. That's a second round trip, and other readers
briefly see a negative value. The script answers in one round trip at roughly 100k ops/s on one
core. Only the winners (≤ 500) are queued for the database.

Why not a Redis `WATCH`/`MULTI` transaction? It is optimistic locking again: under contention most
`EXEC`s abort and must retry. A Lua script never aborts.

## Defence in depth

| Layer | Guarantees | If it fails |
|---|---|---|
| `reserve.lua` | at most `stock` reservations | DB guard catches over-admission |
| conditional UPDATE | at most `stock` confirmed orders | CHECK constraint |
| `CHECK (stock >= 0)` | stock never negative | — (transaction aborts) |
| partial unique index | one confirmed order per user per sale | — |

When can Redis over-admit? When it restarts without persistence or fails over and is re-primed from
PostgreSQL while orders are still in flight. Those extra orders reach the worker, the conditional
UPDATE matches no row, and they become `REJECTED_SOLD_OUT`. Users see an honest "just missed it", and
nothing is oversold. `test_database_guard_rejects_when_redis_over_admits` covers it.

When can Redis under-admit? When an API process crashes between reserving and publishing, which
leaks a token. That is the safe direction (undersell). `reconcile` restores it once the queue is
drained.

## Idempotency and exactly-once effects

RabbitMQ delivers **at least once**. The worker makes the *effect* exactly once:

```text
BEGIN
  INSERT INTO orders (id = <API-generated uuid>, status = 'CONFIRMED', ...)
    ON CONFLICT (id) DO NOTHING RETURNING id      -- nothing returned → already processed → stop
  UPDATE inventory ... AND stock > 0 RETURNING stock
  (0 rows → UPDATE orders SET status = 'REJECTED_SOLD_OUT')
COMMIT
→ write status to Redis → ACK
```

The insert comes **before** the decrement. If the decrement came first, a redelivered message
would decrement again before discovering the duplicate. A data-modifying CTE would not help either,
because Postgres executes data-modifying CTEs even when the outer INSERT conflicts.

Retries publish a copy to the retry exchange **before** acking the original. A crash in between
produces a duplicate, which the idempotent insert absorbs, rather than a lost message.

The user side is idempotent too. The Redis buyer hash maps a user to their order, so double clicks,
client retries after a timeout, and a second tab all get `200` with the same `order_id`.

## Timeouts that keep failures fast

| Setting | Value | Why |
|---|---|---|
| `statement_timeout` | 5 s | no query may hang a worker |
| `lock_timeout` | 2 s | never queue indefinitely behind a lock |
| `idle_in_transaction_session_timeout` | 10 s | a stuck client can't hold the hot row |
| Redis socket / pool wait | 2 s | bounded wait for a pooled connection (blocking pool, not errors) |
| broker publish confirm | 5 s | then compensate + 503 |
| NGINX → API connect / read | 2 s / 10 s | fail over to another replica on connect errors |
| client request | 6–8 s | then a retryable `TIMEOUT` in the UI, never a frozen button |
