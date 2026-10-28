# Single-host AWS deployment

This profile runs the full application on **one EC2 host** in `ap-south-1`, with CloudFront as the
public HTTPS endpoint. Docker Compose runs NGINX, two API containers, one worker, Redis, RabbitMQ,
and PostgreSQL together on that host. It is intended for evaluation and low traffic; it is not a
high-availability or 100,000-request capacity environment.

The diagram is in [architecture-single-host-aws.svg](architecture-single-host-aws.svg). The regular Terraform
stack in `infra/terraform` is a separate production-shaped design with ECS, ALB, and managed data
services; its costs and operating requirements are different.

## Provision

Requirements: Git, Terraform 1.10 or newer, and AWS CLI credentials with permission to create the
resources in `infra/aws-single-host`. Review the AWS pricing and account billing limits before
provisioning; credits and charges vary by account, region, and usage.

From the repository root in PowerShell:

```powershell
aws sts get-caller-identity
git archive --format=zip --output=infra/aws-single-host/source.zip HEAD
terraform -chdir=infra/aws-single-host init
terraform -chdir=infra/aws-single-host apply -var="source_zip_path=source.zip"
terraform -chdir=infra/aws-single-host output -raw app_url
```

The deployment defaults to the resource prefix `flashsale-single-host`. If managing an existing
stack, keep its original `resource_name_prefix` in the local, git-ignored
`infra/aws-single-host/terraform.tfvars`; changing resource names can replace AWS resources.

`git archive` packages the committed source at `HEAD`; commit changes before creating the archive.
Terraform uploads the archive to a private encrypted S3 bucket. EC2 downloads it using a narrowly
scoped instance role, builds the container images, and starts the Compose stack. Terraform outputs
the CloudFront URL before the first boot may have finished building the images, so allow several
minutes for initial setup before opening the URL.

The Terraform state and local archive are required to manage or destroy the stack. The source
checksum is embedded in EC2 user data; changing the archive and applying the change replaces the
instance, including its local database files. Review the plan before applying source changes. For a
code-only rollout that must retain data, use Systems Manager to update the files and rebuild the
needed containers on the existing host.

## Deployment scope

- CloudFront provides the public HTTPS endpoint, caches frontend assets, and forwards `/api/*`
  without caching.
- The EC2 security group accepts the NGINX origin port only from CloudFront's managed origin-facing
  prefix list. CloudFront adds a private origin-verification header.
- The EC2 root volume is encrypted. Instance administration uses Systems Manager; no SSH ingress
  rule is created.
- PostgreSQL, Redis, RabbitMQ, APIs, worker, and NGINX share one host and one failure domain.
- No ALB, NAT gateway, WAF, ECS/Fargate, RDS, ElastiCache, or Amazon MQ is provisioned by this
  profile. Those are described by the production-shaped stack in `infra/terraform`.
- The measured local test report is not a benchmark of this single-host AWS deployment. It
  does not prove the case-study goal of 100,000 concurrent requests in 10 seconds.

## Tear down

From the repository root, while `infra/aws-single-host/source.zip` still exists:

```powershell
terraform -chdir=infra/aws-single-host destroy -var="source_zip_path=source.zip"
```

Terraform removes the EC2 instance, CloudFront distribution, and related resources. CloudFront
deletion can take several minutes. Keep the state until the destroy operation completes.
