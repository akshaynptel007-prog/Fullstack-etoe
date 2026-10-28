# AWS free-plan demo

This profile runs the full application on **one EC2 host** in `ap-south-1`, with CloudFront as the
public HTTPS endpoint. Docker Compose runs NGINX, two API containers, one worker, Redis, RabbitMQ,
and PostgreSQL together on that host. It is for a reviewer demo, not a high-availability or
100,000-request capacity environment.

The diagram is in [architecture-free-demo.svg](architecture-free-demo.svg). The regular Terraform
stack in `infra/terraform` is a separate production-shaped design with ECS, ALB, and managed data
services; its costs and operating requirements are different.

## Provision

Requirements: Git, Terraform 1.10 or newer, AWS CLI credentials with permission to create the
resources in `infra/free-demo`, and an active AWS Free plan credit balance. AWS credits are not an
AWS cost guarantee; monitor the Billing page and destroy the stack after the demo.

From the repository root in PowerShell:

```powershell
aws sts get-caller-identity
git archive --format=zip --output=infra/free-demo/source.zip HEAD
terraform -chdir=infra/free-demo init
terraform -chdir=infra/free-demo apply -var="source_zip_path=source.zip"
terraform -chdir=infra/free-demo output -raw app_url
```

`git archive` packages the committed source at `HEAD`; commit changes before creating the archive.
Terraform uploads the archive to a private encrypted S3 bucket. EC2 downloads it using a narrowly
scoped instance role, builds the container images, and starts the Compose stack. Terraform outputs
the CloudFront URL before the first boot may have finished building the images, so allow several
minutes for initial setup before opening the URL.

For an update, create a fresh archive from the desired commit and re-run `terraform apply` with the
same source path. The Terraform state and the local archive are needed to update or destroy the
stack; do not delete them first.

## Demo scope

- CloudFront provides the public HTTPS endpoint, caches frontend assets, and forwards `/api/*`
  without caching.
- The EC2 security group accepts the NGINX origin port only from CloudFront's managed origin-facing
  prefix list. CloudFront adds a private origin-verification header.
- The EC2 root volume is encrypted. Instance administration uses Systems Manager; no SSH ingress
  rule is created.
- PostgreSQL, Redis, RabbitMQ, APIs, worker, and NGINX share one host and one failure domain.
- No ALB, NAT gateway, WAF, ECS/Fargate, RDS, ElastiCache, or Amazon MQ is provisioned by this
  profile. Those are described by the production-shaped stack in `infra/terraform`.
- The measured local test report is not a benchmark of this single-host AWS demo. This deployment
  does not prove the case-study goal of 100,000 concurrent requests in 10 seconds.

## Tear down

From the repository root, while `infra/free-demo/source.zip` still exists:

```powershell
terraform -chdir=infra/free-demo destroy -var="source_zip_path=source.zip"
```

Terraform removes the EC2 instance, CloudFront distribution, and related resources. CloudFront
deletion can take several minutes. Keep the state until the destroy operation completes.
