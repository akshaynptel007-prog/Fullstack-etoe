# Shared helpers for deploy/destroy scripts. Source, don't execute.
# shellcheck shell=bash

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m' C_BOLD=$'\033[1m' C_BLUE=$'\033[34m' C_GREEN=$'\033[32m' C_YELLOW=$'\033[33m' C_RED=$'\033[31m'
else
  C_RESET='' C_BOLD='' C_BLUE='' C_GREEN='' C_YELLOW='' C_RED=''
fi

STEP_NO=0
step() { STEP_NO=$((STEP_NO + 1)); printf '\n%s==> [%d] %s%s\n' "${C_BOLD}${C_BLUE}" "$STEP_NO" "$*" "$C_RESET"; }
info() { printf '    %s\n' "$*"; }
ok()   { printf '    %s✓ %s%s\n' "$C_GREEN" "$*" "$C_RESET"; }
warn() { printf '    %s! %s%s\n' "$C_YELLOW" "$*" "$C_RESET" >&2; }
die()  { printf '\n%s✗ %s%s\n' "$C_RED" "$*" "$C_RESET" >&2; exit 1; }

on_error() {
  local exit_code=$? line=$1
  printf '\n%s✗ failed at line %s (exit %s): %s%s\n' "$C_RED" "$line" "$exit_code" "$BASH_COMMAND" "$C_RESET" >&2
  exit "$exit_code"
}

require() {
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || die "'$cmd' is required but not installed"
  done
}

# version_ge 1.10.2 1.10.0 -> true
version_ge() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]; }

resolve_aws_context() {
  PROJECT_NAME="${PROJECT_NAME:-flashsale}"
  ENVIRONMENT="${ENVIRONMENT:-dev}"
  AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region 2>/dev/null || true)}}"
  AWS_REGION="${AWS_REGION:-us-east-1}"
  export AWS_REGION AWS_DEFAULT_REGION="$AWS_REGION" AWS_PAGER=""

  local identity
  identity="$(aws sts get-caller-identity --query '[Account,Arn]' --output text 2>/dev/null)" \
    || die "AWS CLI is not authenticated. Run 'aws configure' or 'aws sso login' first."
  ACCOUNT_ID="$(cut -f1 <<<"$identity")"
  # shellcheck disable=SC2034 # used by deploy.sh
  CALLER_ARN="$(cut -f2 <<<"$identity")"
  STATE_BUCKET="${TF_STATE_BUCKET:-${PROJECT_NAME}-${ENVIRONMENT}-tfstate-${ACCOUNT_ID}-${AWS_REGION}}"
  STATE_KEY="${PROJECT_NAME}/${ENVIRONMENT}/terraform.tfstate"
}

tf() { terraform -chdir="$TF_DIR" "$@"; }

tf_init() {
  tf init -input=false -reconfigure \
    -backend-config="bucket=${STATE_BUCKET}" \
    -backend-config="key=${STATE_KEY}" \
    -backend-config="region=${AWS_REGION}" \
    -backend-config="encrypt=true" \
    -backend-config="use_lockfile=true" >/dev/null
}
