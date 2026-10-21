#!/usr/bin/env bash
# Imitates Cloud Scheduler -> Cloud Run Job locally: runs the worker as a
# one-shot container (`docker compose run --rm worker`) on a fixed interval.
# Ctrl+C to stop.
#
# Usage: scripts/run-worker-loop.sh [interval_seconds]
# Default interval matches production's "* * * * *" Cloud Scheduler cadence.
set -euo pipefail

INTERVAL_SECONDS="${1:-${WORKER_LOOP_INTERVAL_SECONDS:-60}}"

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "Running worker every ${INTERVAL_SECONDS}s (Ctrl+C to stop)..."
while true; do
  docker compose run --rm worker
  echo "Sleeping ${INTERVAL_SECONDS}s until next run..."
  sleep "$INTERVAL_SECONDS"
done
