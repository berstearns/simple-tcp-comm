#!/usr/bin/env bash
# migrate.sh — idempotent DB migrations for worker-local databases.
#
# Runs on every update via supervisor.sh.  Every operation here MUST be
# safe to re-run (use IF NOT EXISTS / check column existence).
#
# The script sources .env so it knows where the DBs live.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

log() { echo "[migrate $(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# ── Load DB paths from .env ──────────────────────────────────
# Re-use the same QUEUE_DBS format the worker uses:
#   QUEUE_DBS=main=/var/lib/myapp/main.db,logs=/var/lib/myapp/logs.db
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Parse QUEUE_DBS into an associative array
declare -A DBS
if [ -n "${QUEUE_DBS:-}" ]; then
    IFS=',' read -ra PAIRS <<< "$QUEUE_DBS"
    for pair in "${PAIRS[@]}"; do
        key="${pair%%=*}"
        val="${pair#*=}"
        DBS["$key"]="$val"
    done
else
    DBS[main]="/var/lib/myapp/main.db"
    DBS[logs]="/var/lib/myapp/logs.db"
fi

# ── Helper: run idempotent SQL against a DB ──────────────────
run_sql() {
    local db_path="$1"
    local description="$2"
    local sql="$3"

    if [ ! -f "$db_path" ]; then
        log "SKIP ($description): $db_path does not exist yet"
        return 0
    fi

    if sqlite3 "$db_path" "$sql"; then
        log "OK   $description"
    else
        log "FAIL $description"
        return 1
    fi
}

# Helper: add a column if it doesn't already exist
add_column_if_missing() {
    local db_path="$1"
    local table="$2"
    local column="$3"
    local col_type="$4"

    if [ ! -f "$db_path" ]; then
        return 0
    fi

    local existing
    existing=$(sqlite3 "$db_path" "PRAGMA table_info($table);" | cut -d'|' -f2)
    if echo "$existing" | grep -qw "$column"; then
        log "SKIP column $table.$column already exists"
    else
        sqlite3 "$db_path" "ALTER TABLE $table ADD COLUMN $column $col_type;"
        log "OK   added $table.$column ($col_type)"
    fi
}

# ── Migrations ───────────────────────────────────────────────
# Add new migrations below.  Each must be idempotent.
#
# Examples:
#
#   run_sql "${DBS[main]}" "create users table" \
#       "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT);"
#
#   add_column_if_missing "${DBS[main]}" "users" "email" "TEXT"

log "running migrations..."
log "databases: ${!DBS[*]}"

run_sql "${DBS[main]}" "create users table" \
    "CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );"

run_sql "${DBS[main]}" "create learning_sessions table" \
    "CREATE TABLE IF NOT EXISTS learning_sessions (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        topic TEXT,
        started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        ended_at DATETIME,
        status TEXT DEFAULT 'active'
    );"

log "migrations complete"
