# Imitates Cloud Scheduler -> Cloud Run Job locally: runs the worker as a
# one-shot container (`docker compose run --rm worker`) on a fixed interval.
# Ctrl+C to stop.
#
# Usage: scripts/run-worker-loop.ps1 [-IntervalSeconds 60]
# Default interval matches production's "* * * * *" Cloud Scheduler cadence.
param(
    [int]$IntervalSeconds = 60
)

Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "Running worker every $IntervalSeconds s (Ctrl+C to stop)..."
while ($true) {
    docker compose run --rm worker
    Write-Host "Sleeping $IntervalSeconds s until next run..."
    Start-Sleep -Seconds $IntervalSeconds
}
