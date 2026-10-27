# Performance and load testing

## Running the spike test

```bash
make loadtest                              # defaults below
USERS=10000 STOCK=500 RATE=2000 DURATION=15s ./loadtest/run.sh
```

`loadtest/run.sh`:

1. starts the stack with `docker-compose.loadtest.yml`. It raises the **per-IP** limits, since every
   virtual user shares the k6 container's IP; keeps the **per-user** limits; scales the API to 6
   replicas; and sets NGINX access logs to errors only;
2. bulk-creates `USERS` accounts and mints their JWTs (`python -m app.cli seed-loadtest-users`);
3. resets the sale to open 3 s later with `STOCK` units;
4. runs `loadtest/k6/flash-sale.js`: a ramp to `RATE` checkout req/s from random users (many click
   repeatedly), plus 500 status polls/s;
5. waits for the queue to drain and runs `python -m app.cli verify-sale`, which fails if
   `confirmed > total_stock` or `confirmed + db_stock ≠ total_stock`.

k6 thresholds (all must pass): zero failed requests (anything except 200/202/409/429 counts as a
failure), checkout p95 < 250 ms and p99 < 1 s, status p95 < 200 ms, **accepted ≤ stock**, zero
dropped iterations.

## Results (local, single laptop: 18 threads, 6 × 1-vCPU API containers)

| Run | Checkout rate | Result |
|---|---|---|
| default | 1,500 req/s for 10 s (+500 status/s) — 25,000 requests | **500 accepted, 500 confirmed, 0 oversold, 0 errors, 0 dropped**; checkout p50 2.5 ms · p95 52 ms · p99 560 ms; status p95 0.8 ms |
| stress | 3,000 req/s | laptop saturated: queueing pushes p95 to seconds and some requests hit k6's 10 s timeout, **but still exactly 500/500 sold, 0 oversold** |

Correctness does not degrade under overload; only latency does. Fixing latency is a capacity question
(see below).

### Capacity math for the case study

A single 1-vCPU API process answers **≈ 1,000 checkouts/s** at sub-millisecond median latency up to
≈ 600 req/s (measured with k6 straight at one container). The sold-out path costs about 0.45 ms of
server CPU per request.

100,000 requests in 10 s is about **10,000 req/s**. At ~60% target utilisation that needs
**≈ 15–17 API tasks (1 vCPU each)**. Autoscaling reacts in minutes, but the spike lasts seconds, so
the AWS stack exposes `prewarm_schedules` to scale out **before** 8:00 PM and back in afterwards.
Workers are not on the spike's critical path: they persist ~500 orders.

Redis does ≈ 2 operations per checkout, about 20k ops/s at peak. One ElastiCache node handles
100k+ simple ops/s. PostgreSQL sees ≈ 500 short transactions in total.

## Profiling story: from p95 2 s to 52 ms

The first spike run passed correctness but failed latency (p95 1.2 s at 3 replicas, 2.1 s at 6).
Throughput did not improve with more replicas, so the bottleneck was not where it looked.

| Step | Evidence | Fix |
|---|---|---|
| 1 | `cProfile`: 12 `run_sync_in_worker_thread` calls per request | FastAPI runs plain `def` dependencies in a **threadpool**. `get_resources`, `current_user_id` and `request_ip` became `async def` and now run inline on the event loop |
| 2 | 3 Redis round trips per checkout | per-IP and per-user limits merged into one atomic multi-key Lua call. After sell-out, a 1 s per-process memo skips rate limiting: the reserve script alone answers in 1 round trip and still returns existing orders to their owners |
| 3 | RabbitMQ at **516% CPU** while nearly idle | Erlang schedulers busy-wait by default; disabled with `+sbwt none +sbwtdcpu none +sbwtdio none` |
| 4 | API-side latency histogram: 99.5% < 1 s, but NGINX `upstream_response_time` 2–2.8 s for 7% of requests; host CPU 40–90% idle; no upstream errors | NGINX workers **blocked writing access logs** to stdout when the Docker log driver lagged, stalling every request they held. `NGINX_ACCESS_LOG=errors` keeps only 5xx lines on the hot gateway |
| — | k6 parsing a 1 MB token file in each of 1,500 VUs | `SharedArray` |

The result: **p95 2.05 s → 52 ms** at the same rate, with zero dropped iterations.

Lessons that generalise:

- measure where time is spent (app histogram vs proxy timings) before adding replicas;
- synchronous I/O hides in unexpected places, such as dependency injection and logging;
- log volume is a capacity concern at a gateway. Sample, or log errors only, on the hot path.

## Observability during a test

```bash
make observability     # Prometheus :59090, Grafana :53000 (dashboard "Flash Sale")
```

The dashboard shows checkout outcomes per second, p95 latency per route, worker outcomes, queue depth,
reservation-to-persist lag, rate-limit hits, SSE connections and remaining stock.
