#!/bin/bash
#===============================================================================
# neptune_start.sh — Bootstrap all neptune components in strict-named tmux
#===============================================================================
# ENFORCES: auto-docs/deploy/RULES.md
#
# Creates tmux session "stcp" with:
#   window "queue"   → pane "queue-server"     → python3 server.py (:9999)
#   window "archive" → pane "archive-receiver"  → python3 receiver.py (:8080)
#
# Usage:
#   bash auto-docs/deploy/neptune_start.sh
#   bash auto-docs/deploy/neptune_start.sh /custom/archive.db
#
# After:
#   tmux attach -t stcp
#===============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "$REPO_DIR"

# ── Config ───────────────────────────────────────────────────
SESSION="stcp"
ARCHIVE_DB="${1:-/data/archive.db}"

# ── Strict names (from RULES.md — do not change) ────────────
WIN_QUEUE="queue"
WIN_ARCHIVE="archive"
PANE_QUEUE="queue-server"
PANE_ARCHIVE="archive-receiver"

# ── Preflight ────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}═══ neptune_start.sh ═══${NC}"
echo -e "  repo:       ${REPO_DIR}"
echo -e "  session:    ${SESSION}"
echo -e "  archive_db: ${ARCHIVE_DB}"
echo ""

if ! command -v tmux &>/dev/null; then
    echo -e "${RED}ERROR: tmux not installed${NC}"; exit 1
fi
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}ERROR: python3 not installed${NC}"; exit 1
fi
if [[ ! -f "${REPO_DIR}/server.py" ]]; then
    echo -e "${RED}ERROR: server.py not found in ${REPO_DIR}${NC}"; exit 1
fi
if [[ ! -f "${REPO_DIR}/archive_receiver/json_zlib/receiver.py" ]]; then
    echo -e "${RED}ERROR: archive_receiver/json_zlib/receiver.py not found${NC}"; exit 1
fi

ARCHIVE_DIR="$(dirname "$ARCHIVE_DB")"
if [[ ! -d "$ARCHIVE_DIR" ]]; then
    mkdir -p "$ARCHIVE_DIR"
    echo -e "  created: ${ARCHIVE_DIR}"
fi

echo -e "  ${GREEN}preflight passed${NC}"
echo ""

# ── Kill old session ─────────────────────────────────────────
if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
    echo -e "  killed old session: ${SESSION}"
fi

# ── Window 1: queue server ───────────────────────────────────
tmux new-session -d -s "$SESSION" -n "$WIN_QUEUE" -c "$REPO_DIR"
tmux select-pane -t "${SESSION}:${WIN_QUEUE}" -T "$PANE_QUEUE"
tmux send-keys -t "${SESSION}:${WIN_QUEUE}" \
    "cd ${REPO_DIR} && python3 server.py" C-m

# ── Window 2: archive receiver ───────────────────────────────
tmux new-window -t "$SESSION" -n "$WIN_ARCHIVE" -c "$REPO_DIR"
tmux select-pane -t "${SESSION}:${WIN_ARCHIVE}" -T "$PANE_ARCHIVE"
tmux send-keys -t "${SESSION}:${WIN_ARCHIVE}" \
    "cd ${REPO_DIR} && ARCHIVE_DB=${ARCHIVE_DB} python3 archive_receiver/json_zlib/receiver.py" C-m

# ── Select queue window as default ───────────────────────────
tmux select-window -t "${SESSION}:${WIN_QUEUE}"

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
