#!/usr/bin/env bash
# migrate.sh — idempotent DB migrations for worker-local databases.
#
# Runs on every update via supervisor.sh.  Every operation here MUST be
# safe to re-run (use IF NOT EXISTS / check column existence).
#
# The script sources .env so it knows where the DBs live.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

log() { echo "[migrate $(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# ── Load DB paths from .env ──────────────────────────────────
# Re-use the same QUEUE_DBS format the worker uses:
#   QUEUE_DBS=main=/var/lib/myapp/main.db,logs=/var/lib/myapp/logs.db
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$REPO_DIR/.env"
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

# ── app7.db — mirrors the Room schema from app7-ocr-enriched-bubbles ──

if [ -n "${DBS[app7]:-}" ]; then
    # Create the DB file if it doesn't exist yet (so run_sql doesn't skip)
    if [ ! -f "${DBS[app7]}" ]; then
        sqlite3 "${DBS[app7]}" "SELECT 1;" 2>/dev/null
        log "OK   created ${DBS[app7]}"
    fi

    run_sql "${DBS[app7]}" "app7: session_events" \
        "CREATE TABLE IF NOT EXISTS session_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eventType TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            durationMs INTEGER,
            chapterName TEXT,
            pageId TEXT,
            pageTitle TEXT,
            synced INTEGER DEFAULT 0
        );"

    run_sql "${DBS[app7]}" "app7: annotation_records" \
        "CREATE TABLE IF NOT EXISTS annotation_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imageId TEXT NOT NULL,
            boxIndex INTEGER NOT NULL,
            boxX REAL NOT NULL,
            boxY REAL NOT NULL,
            boxWidth REAL NOT NULL,
            boxHeight REAL NOT NULL,
            label TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            tapX REAL NOT NULL,
            tapY REAL NOT NULL,
            regionType TEXT NOT NULL DEFAULT 'BUBBLE',
            parentBubbleIndex INTEGER,
            tokenIndex INTEGER,
            synced INTEGER DEFAULT 0
        );"

    run_sql "${DBS[app7]}" "app7: chat_messages" \
        "CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            text TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            synced INTEGER DEFAULT 0
        );"

    run_sql "${DBS[app7]}" "app7: page_interactions" \
        "CREATE TABLE IF NOT EXISTS page_interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interactionType TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            chapterName TEXT,
            pageId TEXT,
            normalizedX REAL,
            normalizedY REAL,
            hitResult TEXT,
            synced INTEGER DEFAULT 0
        );"

    run_sql "${DBS[app7]}" "app7: app_launch_records" \
        "CREATE TABLE IF NOT EXISTS app_launch_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            packageName TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            currentChapter TEXT,
            currentPageId TEXT,
            synced INTEGER DEFAULT 0
        );"

    run_sql "${DBS[app7]}" "app7: settings_changes" \
        "CREATE TABLE IF NOT EXISTS settings_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting TEXT NOT NULL,
            oldValue TEXT NOT NULL,
            newValue TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            synced INTEGER DEFAULT 0
        );"

    run_sql "${DBS[app7]}" "app7: region_translations" \
        "CREATE TABLE IF NOT EXISTS region_translations (
            id TEXT PRIMARY KEY NOT NULL,
            imageId TEXT NOT NULL,
            bubbleIndex INTEGER NOT NULL,
            originalText TEXT NOT NULL,
            meaningTranslation TEXT NOT NULL,
            literalTranslation TEXT NOT NULL,
            sourceLanguage TEXT NOT NULL DEFAULT 'ja',
            targetLanguage TEXT NOT NULL DEFAULT 'en'
        );"
fi

log "migrations complete"
