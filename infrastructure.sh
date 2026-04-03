#!/usr/bin/env bash
# infrastructure.sh — set up everything needed to run workers on this machine.
#
# What it does:
#   1. Installs system dependencies (python3, sqlite3, tmux, git)
#   2. Creates database directories and files
#   3. Initializes database schemas
#   4. Sets correct permissions
#   5. Creates .env if missing
#
# Usage:
#   sudo ./infrastructure.sh            # full setup (needs root for /var/lib)
#   ./infrastructure.sh --check         # dry-run: show what's missing
#
# Safe to re-run — all operations are idempotent.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DB_DIR="/var/lib/myapp"
MAIN_DB="$DB_DIR/main.db"
LOGS_DB="$DB_DIR/logs.db"

# ── Colors ──────────────────────────────────────────────────
RED='\033[91m'; GREEN='\033[92m'; YELLOW='\033[93m'; CYAN='\033[96m'
BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

ok()   { echo -e "  ${GREEN}OK${RESET}   $*"; }
skip() { echo -e "  ${DIM}SKIP${RESET} $*"; }
info() { echo -e "  ${CYAN}INFO${RESET} $*"; }
warn() { echo -e "  ${YELLOW}WARN${RESET} $*"; }
fail() { echo -e "  ${RED}FAIL${RESET} $*"; }

# ── Check mode ──────────────────────────────────────────────
if [[ "${1:-}" == "--check" ]]; then
    echo -e "\n${BOLD}Infrastructure check:${RESET}\n"
    errors=0

    for cmd in python3 sqlite3 tmux git; do
        if command -v "$cmd" &>/dev/null; then
            ok "$cmd installed ($(command -v "$cmd"))"
        else
            fail "$cmd not found"
            errors=$((errors + 1))
        fi
    done

    if [[ -d "$DB_DIR" ]]; then
        ok "database directory exists ($DB_DIR)"
    else
        fail "database directory missing ($DB_DIR)"
        errors=$((errors + 1))
    fi

    for db in "$MAIN_DB" "$LOGS_DB"; do
        if [[ -f "$db" ]]; then
            ok "database exists ($db)"
        else
            fail "database missing ($db)"
            errors=$((errors + 1))
        fi
    done

    if [[ -f "$SCRIPT_DIR/.env" ]]; then
        if grep -q "QUEUE_DBS" "$SCRIPT_DIR/.env"; then
            ok ".env has QUEUE_DBS configured"
        else
            warn ".env exists but missing QUEUE_DBS"
            errors=$((errors + 1))
        fi
    else
        fail ".env file missing"
        errors=$((errors + 1))
    fi

    echo ""
    if [[ $errors -eq 0 ]]; then
        echo -e "${GREEN}${BOLD}All checks passed.${RESET}"
    else
        echo -e "${RED}${BOLD}$errors issue(s) found.${RESET} Run: sudo ./infrastructure.sh"
    fi
    exit $errors
fi

# ── Must run as root for /var/lib ───────────────────────────
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}This script needs root to create $DB_DIR${RESET}"
    echo "  Run: sudo ./infrastructure.sh"
    echo "  Or:  ./infrastructure.sh --check  (no root needed)"
    exit 1
fi

echo -e "\n${CYAN}${BOLD}Setting up worker infrastructure...${RESET}\n"

# ── 1. System dependencies ──────────────────────────────────
echo -e "${BOLD}[1/5] System dependencies${RESET}"

install_pkg() {
    local cmd="$1"
    if command -v "$cmd" &>/dev/null; then
        skip "$cmd already installed"
        return
    fi

    if command -v apt-get &>/dev/null; then
        apt-get install -y "$cmd" >/dev/null 2>&1 && ok "installed $cmd (apt)" && return
    fi
    if command -v pacman &>/dev/null; then
        pacman -S --noconfirm "$cmd" >/dev/null 2>&1 && ok "installed $cmd (pacman)" && return
    fi
    if command -v dnf &>/dev/null; then
        dnf install -y "$cmd" >/dev/null 2>&1 && ok "installed $cmd (dnf)" && return
    fi

    fail "could not install $cmd — install it manually"
}

install_pkg python3
install_pkg sqlite3
install_pkg tmux
install_pkg git

# ── 2. Database directory ──────────────────────────────────
echo -e "\n${BOLD}[2/5] Database directory${RESET}"

if [[ -d "$DB_DIR" ]]; then
    skip "$DB_DIR already exists"
else
    mkdir -p "$DB_DIR"
    ok "created $DB_DIR"
fi

# Figure out which user will run the worker
REAL_USER="${SUDO_USER:-$(whoami)}"
chown "$REAL_USER":"$REAL_USER" "$DB_DIR"
chmod 755 "$DB_DIR"
ok "ownership set to $REAL_USER"

# ── 3. Initialize databases with schemas ────────────────────
echo -e "\n${BOLD}[3/5] Database schemas${RESET}"

init_db() {
    local db_path="$1"
    local db_name="$2"
    local schema="$3"

    if [[ -f "$db_path" ]]; then
        # DB exists — just ensure table exists (idempotent)
        sqlite3 "$db_path" "$schema"
        skip "$db_name already exists, schema ensured"
    else
        sqlite3 "$db_path" "$schema"
        chown "$REAL_USER":"$REAL_USER" "$db_path"
        ok "created $db_name ($db_path)"
    fi
}

init_db "$MAIN_DB" "main.db" \
    "CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        name TEXT,
        email TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );"

init_db "$LOGS_DB" "logs.db" \
    "CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY,
        type TEXT,
        msg TEXT,
        ts DATETIME DEFAULT CURRENT_TIMESTAMP
    );"

# ── 4. Ensure .env has QUEUE_DBS ────────────────────────────
echo -e "\n${BOLD}[4/5] Worker configuration (.env)${RESET}"

ENV_FILE="$SCRIPT_DIR/.env"
DBS_LINE="QUEUE_DBS=main=$MAIN_DB,logs=$LOGS_DB"

if [[ -f "$ENV_FILE" ]]; then
    if grep -q "^QUEUE_DBS=" "$ENV_FILE"; then
        skip "QUEUE_DBS already configured in .env"
    else
        echo "$DBS_LINE" >> "$ENV_FILE"
        ok "added QUEUE_DBS to .env"
    fi
else
    cat > "$ENV_FILE" <<EOF
QUEUE_HOST=127.0.0.1
QUEUE_PORT=9999
QUEUE_POLL=2
$DBS_LINE
EOF
    chown "$REAL_USER":"$REAL_USER" "$ENV_FILE"
    ok "created .env with defaults"
fi

# ── 5. Make scripts executable ──────────────────────────────
echo -e "\n${BOLD}[5/5] File permissions${RESET}"

for script in start_supervisor.sh supervisor.sh migrate.sh infrastructure.sh; do
    if [[ -f "$SCRIPT_DIR/$script" ]]; then
        chmod +x "$SCRIPT_DIR/$script"
        ok "$script is executable"
    fi
done

# ── Summary ─────────────────────────────────────────────────
echo -e "\n${GREEN}${BOLD}Infrastructure ready.${RESET}\n"
echo -e "  Databases:"
echo -e "    main → $MAIN_DB"
echo -e "    logs → $LOGS_DB"
echo -e ""
echo -e "  Next steps:"
echo -e "    1. Edit .env to set QUEUE_HOST to your server IP"
echo -e "    2. Run: ${BOLD}./start_supervisor.sh${RESET}"
echo -e ""
