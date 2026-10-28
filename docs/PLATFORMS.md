# Hosting options

This guide compares deployment configurations for the application. Provider pricing, quotas, and
service eligibility change; check current vendor documentation before choosing a plan.

## Recommended setups

| Goal | Frontend | API + worker | PostgreSQL | Redis | RabbitMQ |
|---|---|---|---|---|---|
| **Single-host AWS** (`infra/aws-single-host`) | CloudFront → NGINX on EC2 | Docker Compose on EC2 | Container on EC2 | Container on EC2 | Container on EC2 |
| **Managed AWS** (`infra/terraform`) | Private S3 + CloudFront | ECS Fargate | RDS | ElastiCache | Amazon MQ or hosted broker |
| **Split managed services** | Static CDN host | Container application host | Neon or Supabase | Upstash or Redis Cloud | CloudAMQP or another hosted broker |

The application only needs four URLs: `DATABASE_URL`, `REDIS_URL`, `RABBITMQ_URL`, plus the
frontend's `/api` reaching the API. Any combination works.

## RabbitMQ

| Provider | Plan and operation |
|---|---|
| **CloudAMQP shared broker** | Shared service with plan-specific quotas. Check current connection, message, queue, and retention limits. Use its AMQPS URL as `RABBITMQ_URL`. See [pricing](https://cloudamqp.com/pricing). |
| CloudAMQP LavinMQ | AMQP-compatible broker. Verify support for AMQP 0-9-1 features used here: dead-letter exchanges, TTL queues, and publisher confirms. |
| Stackhero for RabbitMQ | Hosted service; check current [pricing](https://www.stackhero.io/en/services/RabbitMQ/pricing). |
| **Amazon MQ for RabbitMQ** | Managed broker in the AWS VPC with AMQPS. Check current pricing and [supported versions](https://docs.aws.amazon.com/amazon-mq/latest/developer-guide/rabbitmq-version-management.html). |
| Self-hosted broker | The operator owns persistence, upgrades, monitoring, and recovery. |

For low-traffic evaluation, a shared broker can be suitable if its limits cover the API and worker
connections. Use a dedicated broker for load tests or production traffic.

Using it with Terraform:

```hcl
# infra/terraform/terraform.tfvars
rabbitmq_external_url = "amqps://USER:PASSWORD@HOST.rmq.cloudamqp.com/VHOST"
```

With that set, Amazon MQ is not created, and queue-depth autoscaling and the DLQ alarm (which use
Amazon MQ metrics) are skipped. CPU scaling still applies.

## PostgreSQL

| Provider | Notes |
|---|---|
| **Neon** | Managed PostgreSQL with scale-to-zero options. Check current quotas and connection guidance; scale-to-zero can add a cold start. See [pricing](https://neon.com/pricing). |
| Supabase | Managed PostgreSQL. Check current plan limits, pause behavior, and direct connection options. See [pricing](https://supabase.com/pricing). |
| **AWS RDS** | Managed PostgreSQL provisioned by `infra/terraform`; TLS is required by this configuration. |

## Redis

| Provider | Notes |
|---|---|
| **Upstash** | Managed Redis with Lua support. Verify current command quotas and use the `rediss://` URL. See [pricing](https://upstash.com/pricing/redis). |
| Redis Cloud | Managed Redis. Confirm Lua support, connection limits, and persistence for the selected plan. |
| **AWS ElastiCache** | Managed Redis provisioned by `infra/terraform`, with TLS and authentication enabled. |

Requirements: Lua scripting (`EVAL`/`EVALSHA`) and, ideally, `maxmemory-policy noeviction`.

## Frontend

| Provider | Notes |
|---|---|
| **S3 + CloudFront** (this repo) | same-origin `/api` routing through CloudFront, WAF in front of both |
| Cloudflare Pages / Vercel / Netlify | Static hosting with a CDN. Set `VITE_API_BASE_URL=https://api.example.com/api/v1` at build time and configure `CORS_ORIGINS` on the API. Check current plan limits. |

## API and worker

| Provider | Notes |
|---|---|
| **AWS ECS Fargate** (this repo) | autoscaling, Spot workers, scheduled pre-warm |
| Render / Railway / Fly.io | run the same image: `/app/scripts/start-api.sh` for the API, `python -m app.worker` for the worker, `sh -c "alembic upgrade head && python -m app.cli seed"` once |

## AWS account and cost

Account credits, service eligibility, and regional prices vary. Check the AWS Billing console and
Pricing Calculator before provisioning. The managed stack can incur ongoing charges while its
resources exist. Run `./scripts/destroy.sh` when the environment is no longer needed.
