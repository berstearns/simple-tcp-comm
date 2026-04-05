#!/usr/bin/env bash
# supervisor.sh — keeps worker running and auto-updates from a single branch.
#
# Usage:
#   DEPLOY_BRANCH=main deploy/supervisor.sh
#
# Env vars:
#   DEPLOY_BRANCH   — git branch to track          (default: main)
#   UPDATE_INTERVAL — seconds between update checks (default: 300 = 5 min)
#   REPO_DIR        — path to the repo checkout     (default: parent of deploy/)
#   WORKER_CMD      — command to start the worker   (default: python3 worker.py)
#   GRACE_TIMEOUT   — seconds to wait for graceful  (default: 60)
#                     shutdown before SIGKILL

set -euo pipefail

DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
UPDATE_INTERVAL="${UPDATE_INTERVAL:-300}"
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
WORKER_CMD="${WORKER_CMD:-python3 worker.py}"
GRACE_TIMEOUT="${GRACE_TIMEOUT:-60}"

WORKER_PID=""

log() { echo "[supervisor $(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# ── Cleanup on exit ──────────────────────────────────────────
cleanup() {
    log "supervisor exiting, stopping worker..."
    stop_worker
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── Worker lifecycle ─────────────────────────────────────────
start_worker() {
    cd "$REPO_DIR"
    $WORKER_CMD &
    WORKER_PID=$!
    log "started worker (PID $WORKER_PID)"
}

stop_worker() {
    if [ -n "$WORKER_PID" ] && kill -0 "$WORKER_PID" 2>/dev/null; then
        log "sending SIGTERM to worker (PID $WORKER_PID)"
        kill -TERM "$WORKER_PID" 2>/dev/null || true

        # wait up to GRACE_TIMEOUT for clean exit
        local waited=0
        while kill -0 "$WORKER_PID" 2>/dev/null && [ "$waited" -lt "$GRACE_TIMEOUT" ]; do
            sleep 1
            waited=$((waited + 1))
        done

        if kill -0 "$WORKER_PID" 2>/dev/null; then
            log "worker did not stop after ${GRACE_TIMEOUT}s, sending SIGKILL"
            kill -9 "$WORKER_PID" 2>/dev/null || true
        fi
        wait "$WORKER_PID" 2>/dev/null || true
        log "worker stopped"
    fi
    WORKER_PID=""
}

worker_alive() {
    [ -n "$WORKER_PID" ] && kill -0 "$WORKER_PID" 2>/dev/null
}

# ── Git update check ────────────────────────────────────────
check_and_update() {
    cd "$REPO_DIR"

    # fetch can fail (network issues) — caller handles errors
    git fetch origin "$DEPLOY_BRANCH"

    local LOCAL REMOTE
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse "origin/$DEPLOY_BRANCH")

    if [ "$LOCAL" = "$REMOTE" ]; then
        log "up to date ($DEPLOY_BRANCH @ ${LOCAL:0:7})"
        return 1  # no update needed
    fi

    log "update available: ${LOCAL:0:7} → ${REMOTE:0:7}"

    # stop worker before touching files
    stop_worker

    git reset --hard "origin/$DEPLOY_BRANCH"
    log "pulled $DEPLOY_BRANCH @ $(git rev-parse --short HEAD)"

    # run migrations if the script exists
    if [ -x "$REPO_DIR/deploy/migrate.sh" ]; then
        log "running migrate.sh..."
        if bash "$REPO_DIR/deploy/migrate.sh"; then
            log "migrate.sh succeeded"
        else
            log "WARNING: migrate.sh failed (exit $?), starting worker anyway"
        fi
    fi

    return 0  # update was applied
}

# ── Main loop ────────────────────────────────────────────────
log "supervisor starting"
log "  repo:     $REPO_DIR"
log "  branch:   $DEPLOY_BRANCH"
log "  interval: ${UPDATE_INTERVAL}s"
log "  worker:   $WORKER_CMD"

# initial start
start_worker

while true; do
    sleep "$UPDATE_INTERVAL" &
    wait $! 2>/dev/null || true   # interruptible sleep

    # restart worker if it crashed
    if ! worker_alive; then
        log "worker not running — restarting"
        start_worker
    fi

    # check for updates; never let a failure kill the supervisor
    if check_and_update 2>&1; then
        start_worker
    else
        status=$?
        if [ "$status" -gt 1 ]; then
            log "update check failed (exit $status), will retry next cycle"
        fi
        # status=1 means no update needed — do nothing
    fi
done
