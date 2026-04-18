#!/bin/bash
#===============================================================================
# worker_start.sh — Bootstrap all worker components in strict-named tmux
#===============================================================================
# ENFORCES: auto-docs/deploy/RULES.md
#
# Creates tmux session "stcp-w" with:
#   window "worker" → pane "job-worker"  → python3 workers/app7/worker.py
#   window "drain"  → pane "drain-push"  → python3 archive_receiver/json_zlib/drain.py
#
# Usage:
#   bash auto-docs/deploy/worker_start.sh /path/to/simple-tcp-comm
#   bash auto-docs/deploy/worker_start.sh /path/to/simple-tcp-comm .env.custom
#
# After:
#   tmux attach -t stcp-w
#===============================================================================
set -euo pipefail

REPO_DIR="${1:?usage: worker_start.sh /path/to/simple-tcp-comm [.env-file]}"
REPO_DIR="$(cd "$REPO_DIR" && pwd)"
ENV_FILE="${2:-.env}"
cd "$REPO_DIR"

# ── Strict names (from RULES.md — do not change) ────────────
SESSION="stcp-w"
WIN_WORKER="worker"
WIN_DRAIN="drain"
PANE_WORKER="job-worker"
PANE_DRAIN="drain-push"

# ── Preflight ────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}═══ worker_start.sh ═══${NC}"
echo -e "  repo:     ${REPO_DIR}"
echo -e "  env:      ${ENV_FILE}"
echo -e "  session:  ${SESSION}"
echo ""

if ! command -v tmux &>/dev/null; then
    echo -e "${RED}ERROR: tmux not installed${NC}"; exit 1
fi
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}ERROR: python3 not installed${NC}"; exit 1
fi
if [[ ! -f "${REPO_DIR}/${ENV_FILE}" ]]; then
    echo -e "${RED}ERROR: env file not found: ${REPO_DIR}/${ENV_FILE}${NC}"; exit 1
fi
if [[ ! -f "${REPO_DIR}/workers/app7/worker.py" ]]; then
    echo -e "${RED}ERROR: workers/app7/worker.py not found${NC}"; exit 1
fi
if [[ ! -f "${REPO_DIR}/archive_receiver/json_zlib/drain.py" ]]; then
    echo -e "${RED}ERROR: archive_receiver/json_zlib/drain.py not found${NC}"; exit 1
fi

# ── Load env to extract variables ────────────────────────────
set -a; source "${REPO_DIR}/${ENV_FILE}"; set +a

# Validate required vars
: "${QUEUE_HOST:?QUEUE_HOST not set in ${ENV_FILE}}"
: "${QUEUE_PORT:?QUEUE_PORT not set in ${ENV_FILE}}"
: "${QUEUE_DBS:?QUEUE_DBS not set in ${ENV_FILE}}"
: "${WORKER_NAME:?WORKER_NAME not set in ${ENV_FILE}}"

# Extract DB path from QUEUE_DBS (format: app7=/path/to/app7.db)
DB_PATH="${QUEUE_DBS#*=}"

echo -e "  QUEUE_HOST:   ${QUEUE_HOST}"
echo -e "  QUEUE_PORT:   ${QUEUE_PORT}"
echo -e "  WORKER_NAME:  ${WORKER_NAME}"
echo -e "  WORKER_DB:    ${DB_PATH}"
echo ""

# Ensure DB directory exists
DB_DIR="$(dirname "$DB_PATH")"
if [[ ! -d "$DB_DIR" ]]; then
    mkdir -p "$DB_DIR"
    echo -e "  created: ${DB_DIR}"
fi

echo -e "  ${GREEN}preflight passed${NC}"
echo ""

# ── Kill old session ─────────────────────────────────────────
if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
    echo -e "  killed old session: ${SESSION}"
fi

# ── Window 1: job worker ─────────────────────────────────────
tmux new-session -d -s "$SESSION" -n "$WIN_WORKER" -c "$REPO_DIR"
tmux select-pane -t "${SESSION}:${WIN_WORKER}" -T "$PANE_WORKER"
tmux send-keys -t "${SESSION}:${WIN_WORKER}" \
    "cd ${REPO_DIR} && set -a; source ${ENV_FILE}; set +a; python3 workers/app7/worker.py" C-m

# ── Window 2: drain ──────────────────────────────────────────
tmux new-window -t "$SESSION" -n "$WIN_DRAIN" -c "$REPO_DIR"
tmux select-pane -t "${SESSION}:${WIN_DRAIN}" -T "$PANE_DRAIN"
tmux send-keys -t "${SESSION}:${WIN_DRAIN}" \
    "cd ${REPO_DIR} && WORKER_DB=${DB_PATH} ARCHIVE_HOST=${QUEUE_HOST} ARCHIVE_PORT=8080 WORKER_NAME=${WORKER_NAME} python3 archive_receiver/json_zlib/drain.py" C-m

# ── Select worker window as default ──────────────────────────
tmux select-window -t "${SESSION}:${WIN_WORKER}"

# ── Verify ───────────────────────────────────────────────────
echo ""
echo -e "${CYAN}═══ session created ═══${NC}"
echo ""
tmux list-panes -t "$SESSION" -a -F '  #{window_name}:#{pane_title}'
echo ""
echo -e "  attach:  ${GREEN}tmux attach -t ${SESSION}${NC}"
echo -e "  health:  ${GREEN}tmux list-panes -t ${SESSION} -a -F '#{window_name}:#{pane_title} pid=#{pane_pid} cmd=#{pane_current_command}'${NC}"
echo -e "  detach:  Ctrl-B D"
echo -e "  switch:  Ctrl-B n (next window) / Ctrl-B p (prev window)"
