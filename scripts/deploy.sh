#!/usr/bin/env bash
# One-command AWS deployment of the flash-sale platform.
#
# Prerequisites: AWS CLI v2 already authenticated (aws configure / aws sso
# login), Docker running, Terraform >= 1.10. Nothing else (no Node, no
# Python, no jq): images and the SPA are built in Docker.
#
#   ./scripts/deploy.sh                 # provision + build + migrate + publish
#   ./scripts/deploy.sh --plan          # show the Terraform plan only
#   ./scripts/deploy.sh --skip-image    # infra/frontend only, reuse deployed image
#
# Environment overrides: AWS_REGION, PROJECT_NAME (flashsale), ENVIRONMENT (dev),
# CPU_ARCHITECTURE (X86_64|ARM64), TF_STATE_BUCKET. Terraform variables can also
# be set in infra/terraform/terraform.tfvars (see terraform.tfvars.example).
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/infra/terraform"
# shellcheck source=lib/common.sh
source "$ROOT/scripts/lib/common.sh"
trap 'on_error $LINENO' ERR

PLAN_ONLY=false
SKIP_IMAGE=false
SKIP_FRONTEND=false
AUTO_APPROVE=true

usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan) PLAN_ONLY=true ;;
    --skip-image) SKIP_IMAGE=true ;;
    --skip-frontend) SKIP_FRONTEND=true ;;
    --confirm) AUTO_APPROVE=false ;;
    -h | --help) usage ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
  shift
done

# --- 1. Preflight ----------------------------------------------------------------
step "Preflight checks"
require aws terraform docker git curl
docker info >/dev/null 2>&1 || die "Docker daemon is not running"
TF_VERSION="$(terraform version | head -n1 | sed -E 's/^Terraform v([0-9.]+).*/\1/')"
version_ge "$TF_VERSION" "1.10.0" || die "Terraform >= 1.10 required (found $TF_VERSION)"
resolve_aws_context
ok "AWS account $ACCOUNT_ID ($CALLER_ARN), region $AWS_REGION"

CPU_ARCHITECTURE="${CPU_ARCHITECTURE:-X86_64}"
case "$CPU_ARCHITECTURE" in
  X86_64) PLATFORM="linux/amd64" ;;
  ARM64) PLATFORM="linux/arm64" ;;
  *) die "CPU_ARCHITECTURE must be X86_64 or ARM64" ;;
esac

GIT_SHA="$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo nogit)"
if [[ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]]; then
  IMAGE_TAG="${GIT_SHA}-dirty-$(date +%Y%m%d%H%M%S)"
  warn "uncommitted changes: tagging image as $IMAGE_TAG"
else
  IMAGE_TAG="$GIT_SHA"
fi

# --- 2. Remote state ---------------------------------------------------------------
step "Terraform state bucket"
if aws s3api head-bucket --bucket "$STATE_BUCKET" 2>/dev/null; then
  ok "s3://$STATE_BUCKET exists"
else
  info "creating s3://$STATE_BUCKET (versioned, encrypted, private)"
  if [[ "$AWS_REGION" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "$STATE_BUCKET" >/dev/null
  else
    aws s3api create-bucket --bucket "$STATE_BUCKET" \
      --create-bucket-configuration "LocationConstraint=$AWS_REGION" >/dev/null
  fi
  aws s3api wait bucket-exists --bucket "$STATE_BUCKET"
  aws s3api put-bucket-versioning --bucket "$STATE_BUCKET" --versioning-configuration Status=Enabled
  aws s3api put-bucket-encryption --bucket "$STATE_BUCKET" \
    --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-public-access-block --bucket "$STATE_BUCKET" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  ok "state bucket ready"
fi
tf_init
ok "terraform initialised (key $STATE_KEY)"

if $SKIP_IMAGE; then
  IMAGE_TAG="$(tf output -raw image_tag 2>/dev/null || true)"
  [[ -n "$IMAGE_TAG" ]] || die "--skip-image needs an existing deployment (no image_tag in state)"
  info "reusing deployed image tag $IMAGE_TAG"
fi

TF_VARS=(
  -var "project_name=$PROJECT_NAME"
  -var "environment=$ENVIRONMENT"
  -var "aws_region=$AWS_REGION"
  -var "image_tag=$IMAGE_TAG"
  -var "cpu_architecture=$CPU_ARCHITECTURE"
)
APPROVE=()
$AUTO_APPROVE && APPROVE=(-auto-approve)

if $PLAN_ONLY; then
  step "Terraform plan"
  tf plan -input=false "${TF_VARS[@]}"
  exit 0
fi

# --- 3. Image ----------------------------------------------------------------------
step "Container registry"
tf apply -input=false "${APPROVE[@]}" "${TF_VARS[@]}" -target=module.ecr
REPO="$(tf output -raw ecr_repository_url)"
ok "$REPO"

if ! $SKIP_IMAGE; then
  step "Build and push backend image ($PLATFORM, tag $IMAGE_TAG)"
  aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO%%/*}" >/dev/null
  docker build --platform "$PLATFORM" --target runtime -t "$REPO:$IMAGE_TAG" "$ROOT/backend"
  docker push "$REPO:$IMAGE_TAG" >/dev/null
  ok "pushed $REPO:$IMAGE_TAG"
fi

# --- 4. Infrastructure ---------------------------------------------------------------
step "Provision infrastructure (first run: ~15-25 min for RDS, ElastiCache, Amazon MQ, CloudFront)"
tf apply -input=false "${APPROVE[@]}" "${TF_VARS[@]}"

out() { tf output -raw "$1"; }
CLUSTER="$(out ecs_cluster_name)"
API_SERVICE="$(out api_service_name)"
WORKER_SERVICE="$(out worker_service_name)"
MIGRATE_TASK="$(out migrate_task_definition)"
SUBNETS="$(out app_subnet_ids_csv)"
TASK_SG="$(out app_security_group_id)"
PUBLIC_IP="$(out assign_public_ip)"
BUCKET="$(out frontend_bucket)"
DISTRIBUTION="$(out cloudfront_distribution_id)"
APP_URL="$(out app_url)"
SECRET_ARN="$(out app_secret_arn)"
LOG_PREFIX="/ecs/${PROJECT_NAME}-${ENVIRONMENT}"

# --- 5. Migrations -------------------------------------------------------------------
step "Database migrations + seed (one-off ECS task)"
TASK_ARN="$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$MIGRATE_TASK" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$TASK_SG],assignPublicIp=$PUBLIC_IP}" \
  --query 'tasks[0].taskArn' --output text)"
[[ "$TASK_ARN" == arn:* ]] || die "could not start the migration task"
info "task ${TASK_ARN##*/} running…"
aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN"
EXIT_CODE="$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --query 'tasks[0].containers[0].exitCode' --output text)"
if [[ "$EXIT_CODE" != "0" ]]; then
  aws logs tail "$LOG_PREFIX/migrate" --since 15m 2>/dev/null | tail -n 30 || true
  die "migrations failed (exit $EXIT_CODE)"
fi
ok "schema up to date, demo sale seeded"

# --- 6. Frontend -----------------------------------------------------------------------
if ! $SKIP_FRONTEND; then
  step "Build SPA and publish to S3 + CloudFront"
  DIST_DIR="$ROOT/.deploy/dist"
  rm -rf "$DIST_DIR" && mkdir -p "$ROOT/.deploy"
  docker build -f "$ROOT/frontend/Dockerfile" --target build -t "flashsale-web-build:$IMAGE_TAG" "$ROOT"
  CID="$(docker create "flashsale-web-build:$IMAGE_TAG")"
  docker cp "$CID:/app/dist" "$DIST_DIR" >/dev/null
  docker rm "$CID" >/dev/null
  # Hashed assets: cache forever. Old hashes are kept so clients holding the
  # previous index.html keep working mid-deploy. CloudFront compresses itself,
  # so the pre-built .gz twins (for NGINX) are not uploaded.
  aws s3 sync "$DIST_DIR/assets" "s3://$BUCKET/assets" --only-show-errors \
    --exclude "*.gz" --cache-control "public,max-age=31536000,immutable"
  aws s3 sync "$DIST_DIR" "s3://$BUCKET" --only-show-errors --delete \
    --exclude "assets/*" --exclude "*.gz" --cache-control "no-cache"
  aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION" \
    --paths "/index.html" "/" >/dev/null
  ok "SPA published"
fi

# --- 7. Rollout ---------------------------------------------------------------------
step "Wait for ECS services to become stable"
aws ecs wait services-stable --cluster "$CLUSTER" --services "$API_SERVICE" "$WORKER_SERVICE"
ok "api and worker services stable"

step "Smoke test through CloudFront"
for attempt in $(seq 1 30); do
  if curl -fsS -A "flashsale-deploy-smoke/1.0" "$APP_URL/api/v1/sales/current" >/dev/null 2>&1; then
    ok "$APP_URL/api/v1/sales/current responds"
    break
  fi
  [[ $attempt -eq 30 ]] && die "smoke test failed: $APP_URL is not serving the API yet"
  sleep 10
done

cat <<EOF

${C_BOLD}${C_GREEN}Deployed ${PROJECT_NAME}-${ENVIRONMENT} (${IMAGE_TAG})${C_RESET}

  App              ${APP_URL}
  Admin console    ${APP_URL}/admin
  Admin key        aws secretsmanager get-secret-value --secret-id ${SECRET_ARN} \\
                     --query SecretString --output text | python3 -c 'import json,sys; print(json.load(sys.stdin)["ADMIN_API_KEY"])'
  Reset the sale   BASE_URL=${APP_URL} ADMIN_API_KEY=<key> ./scripts/reset-sale.sh --stock 500 --starts-in 300
  Logs             aws logs tail ${LOG_PREFIX}/api --follow
                   aws logs tail ${LOG_PREFIX}/worker --follow
  Tear down        ./scripts/destroy.sh

EOF
