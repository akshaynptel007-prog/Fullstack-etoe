#!/bin/sh
# Starts the API. One process per container is the default: scale by adding
# containers/tasks (stateless), not processes. WEB_CONCURRENCY>1 is supported
# and switches Prometheus to multi-process mode.
set -eu

WORKERS="${WEB_CONCURRENCY:-1}"
if [ "$WORKERS" -gt 1 ]; then
  export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/prometheus}"
  rm -rf "$PROMETHEUS_MULTIPROC_DIR" && mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
fi

exec uvicorn app.main:create_app --factory \
  --host 0.0.0.0 --port "${PORT:-8000}" \
  --workers "$WORKERS" \
  --loop uvloop --http httptools \
  --backlog 4096 \
  --timeout-keep-alive 75 \
  --timeout-graceful-shutdown 20 \
  --no-access-log
