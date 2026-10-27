#!/usr/bin/env bash
# End-to-end spike test on the local stack:
#   USERS signed-in users (default 5000) race for STOCK units (default 500)
#   at RATE checkout requests/s (default 1500) for DURATION (default 10s),
#   then the database is checked: confirmed == stock, nothing oversold.
set -euo pipefail
cd "$(dirname "$0")/.."

USERS="${USERS:-5000}"
STOCK="${STOCK:-500}"
export RATE="${RATE:-1500}" DURATION="${DURATION:-10s}"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.loadtest.yml)
CLI=("${COMPOSE[@]}" run --rm --no-deps --user "$(id -u):$(id -g)" -v "$PWD/loadtest/.data:/data" migrate python -m app.cli)

mkdir -p loadtest/.data loadtest/results

echo "==> Starting the stack with load-test limits"
"${COMPOSE[@]}" up -d --build --wait

echo "==> Seeding ${USERS} users and minting their JWTs"
"${CLI[@]}" seed-loadtest-users --count "$USERS" --out /data/tokens.json

echo "==> Opening the sale: ${STOCK} units, live in 3 s"
"${CLI[@]}" reset-sale --stock "$STOCK" --starts-in 3 --duration 30 >/dev/null
sleep 3

echo "==> Spike: ${RATE} checkout req/s for ${DURATION} + 500 status polls/s"
k6_status=0
"${COMPOSE[@]}" --profile loadtest run --rm --user "$(id -u):$(id -g)" -e STOCK="$STOCK" k6 || k6_status=$?

echo "==> Waiting for the queue to drain and verifying inventory invariants"
"${CLI[@]}" verify-sale --wait 120

if [[ $k6_status -ne 0 ]]; then
  echo "k6 thresholds failed (exit $k6_status) — see output above / loadtest/results/summary.json" >&2
  exit "$k6_status"
fi
echo "==> PASS: no oversell, no 5xx, latency within budget"
