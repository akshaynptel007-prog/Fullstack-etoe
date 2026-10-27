# Requirements traceability

Every requirement in the case study, mapped to where it is implemented and how it is verified.

## 2. Technical core requirements

| Layer | Requirement | Implementation | Verified by |
|---|---|---|---|
| Frontend | Prevent repetitive API spamming from rapid clicks | `frontend/src/hooks/useSingleFlight.ts`, `BuyButton.tsx`; server idempotency in `reserve.lua` | `useSingleFlight.test.tsx`, `BuyButton.test.tsx`, `test_repeat_request_is_idempotent` |
| Frontend | Graceful loading / failed queues without freezing | `useCheckout.ts`, `CheckoutStatus.tsx`, `api/client.ts` (timeouts, retry, Retry-After) | `client.test.ts` |
| Frontend | Bundle < 200 KB | `scripts/check-bundle-size.mjs` (177 KB minified total) | Docker build + CI `frontend` job |
| Frontend | TTI < 1.5 s | inline critical CSS, data preload, code splitting, CDN | CI Lighthouse (`lighthouserc.json`) |
| Gateway | Ingest parallel traffic without drops | stateless replicas behind NGINX/ALB, keep-alive pools, edge micro-cache | `make loadtest`: 0 errors, 0 dropped at 1.5k req/s |
| Gateway | Block bot traffic | WAF managed rules + optional Bot Control; NGINX UA filter | `edge/waf.tf`; manual `curl` → 403 |
| Gateway | Rate-limit bad actors | WAF rate rules, NGINX `limit_req`, Redis sliding window (IP + user) | `test_rate_limit.py`, `test_per_user_rate_limit` |
| Gateway | Distribute load across replicas | NGINX `least_conn` + DNS re-resolve; ALB least-outstanding-requests | compose `api` replicas; `compute/alb.tf` |
| Application | Decouple heavy DB writes from request/response | `services/checkout.py` → RabbitMQ → `worker/processor.py` | `test_checkout_accepts_then_confirms_asynchronously` |
| Application | Stateless clusters | JWT auth (no session store), all state in Redis/PG | horizontal scaling 3 → 6 replicas in load test |
| Application | Event-loop safety | async drivers, bcrypt in threadpool, async dependencies | profiling in [performance.md](performance.md) |
| Database | Exactly 500 sold | Lua gate + conditional UPDATE + CHECK + unique index | `test_burst_of_concurrent_checkouts_never_oversells` (2,000 vs 500), `verify-sale` after k6 |
| Database | No application-level double counters | single counter in Redis (admission) and single row in PG (truth), both decremented atomically | `test_concurrent_reservations_never_exceed_stock` |
| Database | Avoid row-lock timeouts | ≤ stock writes reach PG; single-statement update; no `FOR UPDATE`; fail-fast timeouts | `test_locking_strategies.py` |
| Database | ACID compliance, atomic decrements | worker transaction in `processor.py` | `test_worker_persistence.py` |

## 3. Evaluation framework

| Topic | Where it is answered |
|---|---|
| UI debouncing/throttling | [frontend-performance.md §1](frontend-performance.md#1-click-spam-lock-throttle-idempotency) |
| Asset pre-fetching | [frontend-performance.md §5–6](frontend-performance.md#5-time-to-interactive--15-s) |
| Dynamic polling vs WebSockets | [ADR-0003](adr/0003-sse-with-polling-fallback.md), `useSaleStream.ts` (`pollIntervalMs`) |
| Optimistic UI updates | `store/sale.ts` (`optimisticHold`), `useCheckout.ts` |
| Load balancing strategies | [architecture.md](architecture.md), `nginx/templates/`, `compute/alb.tf` |
| Distributed cache for inventory tokens | `app/lua/reserve.lua`, `services/inventory.py` |
| Message queues + workers | `app/messaging.py`, `app/worker/`, [ADR-0002](adr/0002-rabbitmq-over-kafka.md) |
| Pessimistic vs optimistic locking | [concurrency.md](concurrency.md) + executable comparison |
| Why Lua/atomic beats SELECT-then-UPDATE | [concurrency.md](concurrency.md#why-redis-lua-in-front-of-the-database) |

## 4. Model reference solution

| Step | Implementation |
|---|---|
| A1 Button throttling / lock on first click | `useSingleFlight.ts` |
| A2 CDN for static assets | S3 + CloudFront (`edge/`), NGINX with immutable caching locally |
| A3 State manager + polling/SSE for wait times | zustand stores; SSE + polling; order polling with backoff |
| B1 NGINX / ALB in front of auto-scaling stateless servers | `nginx/`, `compute/alb.tf`, `compute/autoscaling.tf` |
| B2 Redis inventory countdown token | `reserve.lua` (atomic; Lua for check + decrement + dedupe) |
| B3 Async queue, `202 Accepted` + polling URL | `routes/checkout.py`, `messaging.py` |
| C1 Consumers read from the queue | `worker/consumer.py` (prefetch-bounded; `WORKER_PREFETCH=1` for strictly sequential) |
| C2 `UPDATE inventory SET stock = stock - 1 WHERE … AND stock > 0` | `worker/processor.py` (`DECREMENT_STOCK`) |
| C3 No race conditions, no overselling | four-layer defence + idempotent processing ([concurrency.md](concurrency.md)) |

## 5. Grading scorecard ("Exemplary")

| Expectation | Evidence |
|---|---|
| Identifies the N+1 and row-lock bottlenecks | [architecture.md § N+1](architecture.md#n1-and-other-bottlenecks), [concurrency.md](concurrency.md) |
| Async queueing + atomic Redis tokens | sequence diagram in the [README](../README.md#how-a-checkout-works) |
| Deep awareness of bundle optimisation and edge CDNs | [frontend-performance.md](frontend-performance.md), CI budgets |
