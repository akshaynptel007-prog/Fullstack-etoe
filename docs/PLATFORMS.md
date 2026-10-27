# Hosting platforms

Where each piece can run, from "free for a demo" to "production on AWS". Free-tier terms change:
check the vendor's pricing page before relying on a limit. Figures below were checked in October
2026; sources are linked.

## Recommended setups

| Goal | Frontend | API + worker | PostgreSQL | Redis | RabbitMQ |
|---|---|---|---|---|---|
| **Interview demo on AWS (this repo)** | S3 + CloudFront | ECS Fargate | RDS | ElastiCache | Amazon MQ *or* CloudAMQP free |
| **Cheapest AWS** | S3 + CloudFront | ECS Fargate, `enable_nat_gateway=false`, ARM64 | RDS t4g.micro | ElastiCache t4g.micro | **CloudAMQP free** (`rabbitmq_external_url`) |
| **Almost entirely free (non-AWS)** | Cloudflare Pages / Vercel / Netlify | Render / Railway / Fly.io container | Neon or Supabase free | Upstash free | CloudAMQP free |

The application only needs four URLs: `DATABASE_URL`, `REDIS_URL`, `RABBITMQ_URL`, plus the
frontend's `/api` reaching the API. Any combination works.

## RabbitMQ

| Provider | Free? | Notes |
|---|---|---|
| **CloudAMQP — "Little Lemur" (shared)** | **Free** | ≈ 1M messages/month, 20 concurrent connections, 100 queues, 10k queued messages, idle queues removed after 28 days; meant for development ([pricing](https://cloudamqp.com/pricing), [shared-plan limits](https://www.cloudamqp.com/blog/added-limits-for-shared-plans-lemur-tiger.html)). AMQPS URL works directly as `RABBITMQ_URL` |
| CloudAMQP — LavinMQ free plan | Free | AMQP-compatible broker by the same company. Our client uses plain AMQP 0-9-1 features (DLX, TTL, confirms), but verify compatibility before relying on it |
| Stackhero for RabbitMQ | No (paid "Hobby" ≈ $19/mo; no card needed to start) | [pricing](https://www.stackhero.io/en/services/RabbitMQ/pricing) |
| **Amazon MQ for RabbitMQ** | No (≈ $25–30/mo for mq.t3.micro single-instance; check pricing) | managed, in-VPC, AMQPS. `mq.t3.micro` runs the **3.13** series only; RabbitMQ 4.2 needs `mq.m7g` ([version docs](https://docs.aws.amazon.com/amazon-mq/latest/developer-guide/rabbitmq-version-management.html), [pricing](https://aws.amazon.com/amazon-mq/pricing/)) |
| Self-hosted container (Railway, Render, Fly.io, EC2) | trial credits only | you own persistence, upgrades and monitoring |

**Is the free CloudAMQP plan enough?** For a demo, yes. Each API/worker process holds one
connection, so 20 connections covers about 10 tasks. Only *winning* checkouts are published
(≈ 500 per sale), plus retries, so 1M messages/month is plenty. It is a shared instance, though:
don't run a real sale or the load test against it.

Using it with Terraform:

```hcl
# infra/terraform/terraform.tfvars
rabbitmq_external_url = "amqps://USER:PASSWORD@HOST.rmq.cloudamqp.com/VHOST"
```

With that set, Amazon MQ is not created, and queue-depth autoscaling and the DLQ alarm (which use
Amazon MQ metrics) are skipped. CPU scaling still applies.

## PostgreSQL

| Provider | Free tier | Notes |
|---|---|---|
| **Neon** | Free plan: 100 projects, 0.5 GB per project (raised to 1 GB in a late-2026 update according to [this digest](https://releases.sh/collections/serverless-postgres/digest/2026-09-28); [official pricing](https://neon.com/pricing)), scale-to-zero compute | Use `postgresql+asyncpg://…?ssl=require`. Scale-to-zero adds a cold start on the first query |
| Supabase | free project (pauses after inactivity) | plain Postgres; use the direct connection string |
| **AWS RDS** | covered by new-account credits | what this repo provisions |

## Redis

| Provider | Free tier | Notes |
|---|---|---|
| **Upstash** | 256 MB, 500K commands/month ([pricing](https://upstash.com/pricing/redis)) | supports `EVALSHA`/Lua; use the `rediss://` URL. 500K commands ≈ 250K checkouts, fine for demos but not a load test |
| Redis Cloud | small free database | Lua supported |
| **AWS ElastiCache** | covered by new-account credits | what this repo provisions (TLS + AUTH) |

Requirements: Lua scripting (`EVAL`/`EVALSHA`) and, ideally, `maxmemory-policy noeviction`.

## Frontend

| Provider | Notes |
|---|---|
| **S3 + CloudFront** (this repo) | same-origin `/api` routing through CloudFront, WAF in front of both |
| Cloudflare Pages / Vercel / Netlify | free static hosting with a CDN. Set `VITE_API_BASE_URL=https://api.example.com/api/v1` at build time and `CORS_ORIGINS` on the API |

## API and worker

| Provider | Notes |
|---|---|
| **AWS ECS Fargate** (this repo) | autoscaling, Spot workers, scheduled pre-warm |
| Render / Railway / Fly.io | run the same image: `/app/scripts/start-api.sh` for the API, `python -m app.worker` for the worker, `sh -c "alembic upgrade head && python -m app.cli seed"` once |

## AWS account

New AWS customers (accounts created since July 2025) get a credit-based Free Tier: $100 on sign-up,
plus up to $100 more for completing onboarding activities, on a 6-month free plan
([announcement](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/),
[FAQ](https://aws.amazon.com/free/faqs/)). At ≈ $5–6/day, a demo of this stack runs for weeks on
those credits. Free-*plan* accounts can't use some services. If a resource such as Amazon MQ or
ElastiCache is refused, upgrade the account to the paid plan (unused credits still apply).
Remember `./scripts/destroy.sh` afterwards.
