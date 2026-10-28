#!/usr/bin/env bash
# Restock and reschedule the sale (deletes its orders).
#
#   ./scripts/reset-sale.sh --stock 500 --starts-in 60
#   BASE_URL=https://dxxxx.cloudfront.net ADMIN_API_KEY=... ./scripts/reset-sale.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
ADMIN_API_KEY="${ADMIN_API_KEY:-local-admin-key}"
SALE_ID=1
STOCK=500
STARTS_IN=30
DURATION=60

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sale-id) SALE_ID="$2"; shift ;;
    --stock) STOCK="$2"; shift ;;
    --starts-in) STARTS_IN="$2"; shift ;;
    --duration) DURATION="$2"; shift ;;
    -h | --help) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

curl -fsS -X POST "${BASE_URL%/}/api/v1/admin/sales/${SALE_ID}/reset" \
  -A "flashsale-admin-script/1.0" \
  -H "X-Admin-Key: ${ADMIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"stock\": ${STOCK}, \"starts_in_seconds\": ${STARTS_IN}, \"duration_minutes\": ${DURATION}}"
echo
echo "Sale ${SALE_ID}: ${STOCK} units, opens in ${STARTS_IN}s for ${DURATION} min."
