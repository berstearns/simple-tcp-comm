#!/bin/bash
#===============================================================================
# setup_e2e_local.sh — One-command E2E setup: worker + collector in tmux
#===============================================================================
# Creates:
#   - Timestamped dbs/ and offline-collected/ folders
#   - .env file for this run
#   - tmux session "app7-e2e" with 2 panes:
#       pane 0 (top):    worker polling DO queue
#       pane 1 (bottom): collector loop (60s cycle)
#
# Usage:
#   ./setup_e2e_local.sh              # auto-generates timestamp
#   ./setup_e2e_local.sh 20260412     # use a custom tag
#
# After running:
#   tmux attach -t app7-e2e           # watch the pipeline
#   Ctrl-B ↑/↓ to switch panes, Ctrl-B D to detach
#===============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="/home/b/simple-tcp-comm-worker-deploy"
WORKER_PY="${SCRIPT_DIR}/workers/app7-explicit-db-hierarchy_20260409_154552/worker.py"
COLLECTOR_PY="${SCRIPT_DIR}/collector.py"
SESSION="app7-e2e"
WINDOW="pipeline"

# Timestamp
TS="${1:-$(date +%Y%m%d_%H%M%S)}"

DB_DIR="${DEPLOY_DIR}/dbs/${TS}"
ARCHIVE_DIR="${DEPLOY_DIR}/offline-collected/${TS}"
DB_PATH="${DB_DIR}/app7.db"
ARCHIVE_PATH="${ARCHIVE_DIR}/archive.db"
ENV_FILE="${DEPLOY_DIR}/.env.e2e-${TS}"
WORKER_NAME="e2e-${TS}"

echo -e "${CYAN}=== E2E Local Setup ===${NC}"
echo -e "Timestamp:  ${GREEN}${TS}${NC}"
echo -e "Worker DB:  ${DB_DIR}/app7.db"
echo -e "Archive:    ${ARCHIVE_DIR}/archive.db"
echo -e "Env:        ${ENV_FILE}"
echo -e "Worker:     ${WORKER_NAME}"
echo -e "Session:    ${SESSION}:${WINDOW} (pane 0=worker, pane 1=collector)"
echo ""

# ── Preflight checks ────────────────────────────────────────
echo -e "${CYAN}[1/6] Preflight checks${NC}"

if ! command -v tmux &>/dev/null; then
    echo -e "${RED}Error: tmux not installed${NC}"; exit 1
fi
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: python3 not installed${NC}"; exit 1
fi
if [[ ! -f "$WORKER_PY" ]]; then
    echo -e "${RED}Error: worker not found: ${WORKER_PY}${NC}"; exit 1
fi
if [[ ! -f "$COLLECTOR_PY" ]]; then
    echo -e "${RED}Error: collector not found: ${COLLECTOR_PY}${NC}"; exit 1
fi
if [[ ! -f "${SCRIPT_DIR}/archive_schema.sql" ]]; then
    echo -e "${RED}Error: archive_schema.sql not found${NC}"; exit 1
fi

# Test queue connectivity
if timeout 5 python3 -c "
import sys; sys.path.insert(0, '${SCRIPT_DIR}')
import client; r=client.workers(); assert r.get('ok'), 'queue down'
" 2>/dev/null; then
    echo -e "  Queue server:  ${GREEN}reachable${NC}"
else
    echo -e "  Queue server:  ${RED}UNREACHABLE${NC}"
    echo -e "  Check: is your IP in the DO firewall?"
    echo -e "  Run: /home/b/p/all-my-tiny-projects/do-automation/do-firewall add-ip <fw-id> \$(curl -s ifconfig.me)"
    exit 1
fi
echo -e "  ${GREEN}All checks passed${NC}"

# ── Create directories ───────────────────────────────────────
echo -e "${CYAN}[2/6] Creating directories${NC}"
mkdir -p "$DB_DIR" "$ARCHIVE_DIR"
echo -e "  ${DB_DIR}"
echo -e "  ${ARCHIVE_DIR}"

# ── Write env file ───────────────────────────────────────────
echo -e "${CYAN}[3/6] Writing env file${NC}"
cat > "$ENV_FILE" <<EOF
QUEUE_HOST=137.184.225.153
QUEUE_PORT=9999
QUEUE_POLL=2
QUEUE_DBS=app7=${DB_PATH}
WORKER_NAME=${WORKER_NAME}
EOF
echo -e "  ${ENV_FILE}"

# ── Kill old session ─────────────────────────────────────────
echo -e "${CYAN}[4/6] Cleaning up old session${NC}"
if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
    echo -e "  Killed old ${SESSION}"
else
    echo -e "  No old session"
fi

# ── Create tmux session with 2 panes ────────────────────────
echo -e "${CYAN}[5/6] Creating tmux session${NC}"

# Create session — first pane is the worker
tmux new-session -d -s "$SESSION" -n "$WINDOW" -c "$SCRIPT_DIR"

# Get the initial pane ID so we can address it reliably
WORKER_PANE=$(tmux list-panes -t "${SESSION}" -F '#{pane_id}' | head -1)

tmux send-keys -t "$WORKER_PANE" \
    "echo '══════════════════════════════════════'; \
     echo '  WORKER  │  run: ${TS}'; \
     echo '  polling DO queue every 2s'; \
     echo '  DB: ${DB_PATH}'; \
     echo '══════════════════════════════════════'; \
     set -a; source ${ENV_FILE}; set +a; \
     python3 ${WORKER_PY}" C-m

# Split to create collector pane — this becomes the active pane
tmux split-window -t "${SESSION}" -v -c "$SCRIPT_DIR"
COLLECTOR_PANE=$(tmux list-panes -t "${SESSION}" -F '#{pane_id}' | tail -1)

tmux send-keys -t "$COLLECTOR_PANE" \
    "echo '══════════════════════════════════════'; \
     echo '  COLLECTOR  │  run: ${TS}'; \
     echo '  cycle: 60s  │  direct mode'; \
     echo '  archive: ${ARCHIVE_PATH}'; \
     echo '══════════════════════════════════════'; \
     sleep 5; \
     while true; do \
       echo ''; \
       echo '─── collect \$(date +%H:%M:%S) ───'; \
       ARCHIVE_DB=${ARCHIVE_PATH} \
         python3 ${COLLECTOR_PY} collect \
           --direct ${DB_PATH} \
           --worker-name ${WORKER_NAME}; \
       echo ''; \
       echo '─── verify ───'; \
       ARCHIVE_DB=${ARCHIVE_PATH} \
         python3 ${COLLECTOR_PY} verify \
           --direct ${DB_PATH} \
           --worker-name ${WORKER_NAME}; \
       echo ''; \
       echo '─── next cycle in 60s (Ctrl-C to stop) ───'; \
       sleep 60; \
     done" C-m

echo -e "  ${GREEN}Session created: ${SESSION}:${WINDOW}${NC}"
echo -e "    pane 0 (top):    worker"
echo -e "    pane 1 (bottom): collector (60s loop)"

# ── Verify worker registered ────────────────────────────────
echo -e "${CYAN}[6/6] Waiting for worker to register...${NC}"
sleep 3
if timeout 10 python3 -c "
import sys; sys.path.insert(0, '${SCRIPT_DIR}')
import client
r = client.workers()
found = [w for w in r.get('workers',[]) if '${WORKER_NAME}' in w['name']]
if found:
    print(f'  Worker registered: {found[0][\"name\"]}  (seen {found[0][\"last_seen\"]})')
else:
    print('  WARNING: worker not yet visible on queue (may need a few more seconds)')
" 2>/dev/null; then
    true
else
    echo -e "  ${RED}Could not verify worker registration${NC}"
fi

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  READY${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Attach:     ${CYAN}tmux attach -t ${SESSION}${NC}"
echo -e "  Detach:     Ctrl-B D"
echo -e "  Pane up:    Ctrl-B ↑"
echo -e "  Pane down:  Ctrl-B ↓"
echo ""
echo -e "  Launch app: ${CYAN}adb shell am start -n pl.czak.imageviewer.app7/pl.czak.learnlauncher.android.MainActivity --ez auto_sync true${NC}"
echo ""
echo -e "  Then: open the app, browse comics, tap pages, wait 60s."
echo -e "  Watch the worker pane for 'ingesting...' and the collector"
echo -e "  pane for 'OVERALL: PASS'."
echo ""
echo -e "  Worker DB:  ${CYAN}${DB_PATH}${NC}"
echo -e "  Archive:    ${CYAN}${ARCHIVE_PATH}${NC}"
echo -e "  Stop:       ${CYAN}tmux kill-session -t ${SESSION}${NC}"
