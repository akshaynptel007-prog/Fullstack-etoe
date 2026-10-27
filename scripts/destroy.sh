#!/usr/bin/env bash
# Tear down everything deploy.sh created.
#
#   ./scripts/destroy.sh                # asks for confirmation
#   ./scripts/destroy.sh --yes          # no prompt
#   ./scripts/destroy.sh --purge-state  # also delete the Terraform state bucket
#
# Uses the same PROJECT_NAME / ENVIRONMENT / AWS_REGION as deploy.sh.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/infra/terraform"
# shellcheck source=lib/common.sh
source "$ROOT/scripts/lib/common.sh"
trap 'on_error $LINENO' ERR

ASSUME_YES=false
PURGE_STATE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes | -y) ASSUME_YES=true ;;
    --purge-state) PURGE_STATE=true ;;
    -h | --help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

step "Preflight checks"
require aws terraform
resolve_aws_context
aws s3api head-bucket --bucket "$STATE_BUCKET" 2>/dev/null \
  || die "state bucket s3://$STATE_BUCKET not found — nothing deployed for ${PROJECT_NAME}-${ENVIRONMENT} in $AWS_REGION?"
ok "account $ACCOUNT_ID, region $AWS_REGION, stack ${PROJECT_NAME}-${ENVIRONMENT}"

if ! $ASSUME_YES; then
  printf '\n%sThis permanently deletes the %s-%s stack (database included) in %s.%s\n' \
    "$C_RED" "$PROJECT_NAME" "$ENVIRONMENT" "$AWS_REGION" "$C_RESET"
  read -r -p "Type the stack name (${PROJECT_NAME}-${ENVIRONMENT}) to continue: " answer
  [[ "$answer" == "${PROJECT_NAME}-${ENVIRONMENT}" ]] || die "aborted"
fi

step "Terraform destroy (CloudFront takes ~10-15 min to disable and delete)"
tf_init
IMAGE_TAG="$(tf output -raw image_tag 2>/dev/null || echo latest)"
tf destroy -input=false -auto-approve \
  -var "project_name=$PROJECT_NAME" \
  -var "environment=$ENVIRONMENT" \
  -var "aws_region=$AWS_REGION" \
  -var "image_tag=$IMAGE_TAG"
ok "stack destroyed"

if $PURGE_STATE; then
  step "Delete state bucket s3://$STATE_BUCKET"
  for kind in Versions DeleteMarkers; do
    payload="$(aws s3api list-object-versions --bucket "$STATE_BUCKET" \
      --query "{Objects: ${kind}[].{Key: Key, VersionId: VersionId}}" --output json)"
    if [[ "$payload" != *'"Objects": null'* ]]; then
      aws s3api delete-objects --bucket "$STATE_BUCKET" --delete "$payload" >/dev/null
    fi
  done
  aws s3api delete-bucket --bucket "$STATE_BUCKET"
  ok "state bucket deleted"
else
  info "state bucket kept: s3://$STATE_BUCKET (re-run with --purge-state to delete)"
fi
