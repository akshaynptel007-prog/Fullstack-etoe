# Environment variables

**Local:** you don't have to set anything. `docker compose up -d` works with the defaults baked into
`docker-compose.yml`. To override, `cp .env.example .env` and edit. `.env` is gitignored.

**AWS:** you don't set application secrets by hand either. Terraform generates the DB/Redis/RabbitMQ
passwords, the JWT secret and the admin key, stores them in Secrets Manager, and ECS injects them.
You only choose *infrastructure* options in `infra/terraform/terraform.tfvars` (gitignored, copy
`terraform.tfvars.example`).

## What you must fill in

| Scenario | Must set | Where |
|---|---|---|
| Local development | nothing | — |
| Local, exposed beyond your machine | `JWT_SECRET`, `ADMIN_API_KEY`, `POSTGRES_PASSWORD`, `RABBITMQ_PASSWORD` | `.env` |
| AWS, default (Amazon MQ) | nothing (be logged in to the AWS CLI) | — |
| AWS with a free CloudAMQP broker | `rabbitmq_external_url` | `terraform.tfvars` |
| AWS alarm emails | `alarm_email` | `terraform.tfvars` |
| AWS for a real sale date | `prewarm_schedules` | `terraform.tfvars` |
| Running the app outside Docker (e.g. `uv run uvicorn`) | `DATABASE_URL`, `REDIS_URL`, `RABBITMQ_URL` if not using the compose ports | shell / `backend/.env` |

## Application settings (`backend/app/config.py`)

Read from environment variables (case-insensitive) or `backend/.env`.

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `local` | `local` · `test` · `production`. Production refuses default secrets and hides `/docs` |
| `LOG_LEVEL` | `INFO` | JSON logs to stdout |
| `DATABASE_URL` | `postgresql+asyncpg://flash:flash@localhost:55432/flashsale` | asyncpg URL; on AWS includes `?ssl=require` |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `10` | per process |
| `DB_POOL_TIMEOUT_SECONDS` | `5` | wait for a pooled connection |
| `DB_STATEMENT_TIMEOUT_MS` | `5000` | server-side `statement_timeout` (plus `lock_timeout` 2 s) |
| `REDIS_URL` | `redis://localhost:56379/0` | `rediss://:token@host:6379/0` for TLS + AUTH |
| `REDIS_MAX_CONNECTIONS` | `200` | blocking pool size per process |
| `REDIS_SOCKET_TIMEOUT_SECONDS` | `2` | also the max wait for a pooled connection |
| `RABBITMQ_URL` | `amqp://flash:flash@localhost:55672/` | `amqps://…:5671` on Amazon MQ / CloudAMQP |
| `RABBITMQ_NAMESPACE` | `flashsale` | prefix of exchanges/queues (`flashsale.orders`, `.retry`, `.dlq`) |
| `RABBITMQ_QUEUE_TYPE` | `classic` | `quorum` on a 3-node cluster for replicated queues |
| `RABBITMQ_PUBLISH_TIMEOUT_SECONDS` | `5` | wait for the broker confirm, then compensate + 503 |
| `JWT_SECRET` | dev value | ≥ 32 chars in production |
| `JWT_EXPIRES_MINUTES` | `720` | session length |
| `BCRYPT_ROUNDS` | `12` | `4` in tests |
| `ADMIN_API_KEY` | `local-admin-key` | header `X-Admin-Key` for `/api/v1/admin/*` |
| `CORS_ORIGINS` | empty | comma-separated; only needed for `npm run dev` (`http://localhost:5173`) |
| `CLIENT_IP_TRUSTED_HOPS` | `1` | proxies that append to `X-Forwarded-For`: 1 behind NGINX, 2 behind CloudFront → ALB |
| `RATE_LIMIT_ENABLED` | `true` | |
| `RATE_LIMIT_WINDOW_SECONDS` | `10` | sliding window for checkout limits |
| `RATE_LIMIT_CHECKOUT_PER_USER` | `5` | per window |
| `RATE_LIMIT_CHECKOUT_PER_IP` | `200` | per window; generous for campus/mobile NATs |
| `RATE_LIMIT_AUTH_PER_IP` | `30` | per minute (register/login) |
| `BROADCASTER_INTERVAL_MS` | `500` | how often each process reads stock for SSE |
| `SSE_HEARTBEAT_SECONDS` | `15` | keeps proxies from closing idle streams |
| `SSE_MAX_CONNECTIONS_PER_PROCESS` | `5000` | beyond this: 503 → client polls |
| `SALE_CACHE_TTL_SECONDS` | `5` | per-process sale metadata cache |
| `ORDER_POLL_AFTER_MS` | `1000` | hint returned with `202` |
| `ORDER_STATUS_TTL_SECONDS` | `86400` | Redis order-status TTL |
| `WORKER_PREFETCH` | `16` | in-flight messages per worker (`1` = strictly sequential) |
| `WORKER_MAX_RETRIES` | `5` | then dead-letter |
| `WORKER_RETRY_DELAY_MS` | `2000` | TTL of the retry queue |
| `WORKER_METRICS_PORT` | `9100` | Prometheus endpoint of the worker |
| `WORKER_SHUTDOWN_GRACE_SECONDS` | `25` | drain time on SIGTERM |
| `SEED_SALE_STOCK` | `500` | demo sale created by `python -m app.cli seed` |
| `SEED_SALE_STARTS_IN_SECONDS` | `120` (local) / `900` (AWS) | |
| `SEED_SALE_DURATION_MINUTES` | `60` / `120` | |
| `WEB_CONCURRENCY` | `1` | uvicorn processes per container (scale with replicas instead) |

## Docker Compose (`.env`)

| Variable | Default | Description |
|---|---|---|
| `COMPOSE_PROJECT_NAME` | `flashsale` | |
| `WEB_PORT` | `8080` | storefront + API |
| `POSTGRES_HOST_PORT` / `REDIS_HOST_PORT` / `RABBITMQ_HOST_PORT` / `RABBITMQ_MGMT_HOST_PORT` | `55432` / `56379` / `55672` / `15672` | bound to 127.0.0.1 |
| `API_REPLICAS` / `WORKER_REPLICAS` | `3` / `2` | (`6` API replicas in the load-test overlay) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `flash` / `flash` / `flashsale` | |
| `RABBITMQ_USER` / `RABBITMQ_PASSWORD` | `flash` / `flash` | |
| `PROMETHEUS_HOST_PORT` / `GRAFANA_HOST_PORT` / `GRAFANA_ADMIN_PASSWORD` | `59090` / `53000` / `admin` | observability profile |

### NGINX gateway (`web` service)

| Variable | Default | Description |
|---|---|---|
| `NGINX_API_RATE` / `NGINX_API_BURST` | `100r/s` / `200` | per-IP, all API routes |
| `NGINX_CHECKOUT_RATE` / `NGINX_CHECKOUT_BURST` | `20r/s` / `40` | per-IP, checkout only |
| `NGINX_BOT_FILTER` | `1` | 403 for empty / scanner / scripted user agents at checkout (`curl`, `python-requests`, …) |
| `NGINX_ACCESS_LOG` | `all` | `errors` = log only 5xx (use under heavy load) |
| `API_UPSTREAM` / `NGINX_RESOLVER` | `api:8000` / `127.0.0.11` | Docker DNS; replicas are re-resolved every 10 s |

> Tip: the bot filter blocks `curl` at the checkout endpoint. Pass a browser-like
> `-A "Mozilla/5.0"` when testing by hand.

### Frontend build

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | `/api/v1` | same-origin by design (NGINX locally, CloudFront on AWS) |
| `VITE_PROXY_TARGET` | `http://localhost:8080` | where `npm run dev` proxies `/api` |

## Terraform (`infra/terraform/terraform.tfvars`)

| Variable | Default | Description |
|---|---|---|
| `project_name` / `environment` | `flashsale` / `dev` | resource prefix |
| `aws_region` | `us-east-1` | set by `deploy.sh` from `AWS_REGION` / CLI config |
| `image_tag` | `latest` | set by `deploy.sh` (git SHA) |
| `vpc_cidr` / `az_count` | `10.40.0.0/16` / `2` | |
| `enable_nat_gateway` | `true` | `false` = public subnets + public IPs (cheaper) |
| `cpu_architecture` | `X86_64` | or `ARM64` (set via `CPU_ARCHITECTURE` for `deploy.sh`) |
| `api` | 0.5 vCPU / 1 GB, 2–10 tasks, CPU 55%, 1000 req/target | |
| `worker` | 0.25 vCPU / 0.5 GB, 1–4 tasks, Spot, prefetch 16 | |
| `prewarm_schedules` | `[]` | scheduled scale-out before a sale |
| `app_env` | rate limits + seed settings | extra non-secret env for containers |
| `db` | `db.t4g.micro`, PG 16, 20 GB, single-AZ | |
| `redis` | `cache.t4g.micro`, 7.1, 1 node | |
| `mq` | `mq.t3.micro`, RabbitMQ 3.13 | t3.micro supports the 3.13 series only |
| `rabbitmq_external_url` | empty | set to use CloudAMQP etc. instead of Amazon MQ |
| `secrets_recovery_window_days` | `0` | immediate delete on destroy |
| `enable_waf` / `enable_bot_control` | `true` / `false` | |
| `waf_rate_limit_per_ip` / `waf_checkout_rate_limit_per_ip` | `600` / `60` | per IP per minute |
| `cloudfront_price_class` | `PriceClass_200` | includes India edges |
| `log_retention_days` | `14` | |
| `alarm_email` | empty | SNS email for alarms |

`deploy.sh` also reads `AWS_REGION`, `PROJECT_NAME`, `ENVIRONMENT`, `CPU_ARCHITECTURE` and
`TF_STATE_BUCKET` from the environment.

## Secrets created on AWS

Secrets Manager secret `<project>-<env>/app` (JSON):

| Key | Source |
|---|---|
| `DATABASE_URL` | RDS endpoint + generated password, `?ssl=require` |
| `REDIS_URL` | ElastiCache primary endpoint + generated AUTH token (`rediss://`) |
| `RABBITMQ_URL` | Amazon MQ AMQPS endpoint + generated password, or your `rabbitmq_external_url` |
| `JWT_SECRET` | 64 random chars |
| `ADMIN_API_KEY` | 40 random chars (read it with the command printed by `deploy.sh`) |
