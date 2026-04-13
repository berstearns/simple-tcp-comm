#!/bin/bash
#===============================================================================
# health_check.sh — Verify all components are running with correct names
#===============================================================================
# ENFORCES: auto-docs/deploy/RULES.md
#
# Usage:
#   bash auto-docs/deploy/health_check.sh              # check local machine
#   bash auto-docs/deploy/health_check.sh neptune       # check neptune via ssh
#   bash auto-docs/deploy/health_check.sh all            # check both
#
# Exit codes:
#   0 = all components running
#   1 = something is down
#===============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'; NC='\033[0m'

FAIL=0

check_pane() {
    local session="$1"
    local window="$2"
    local expected_title="$3"
    local label="$4"
    local ssh_prefix="${5:-}"

    local cmd="${ssh_prefix}tmux list-panes -t ${session}:${window} -F '#{pane_title}|#{pane_current_command}' 2>/dev/null"
    local result
    result=$(eval "$cmd" 2>/dev/null) || result=""

    if [[ -z "$result" ]]; then
        echo -e "  ${RED}DOWN${NC}  ${label}  (session ${session} window ${window} not found)"
        FAIL=1
        return
    fi

    local title="${result%%|*}"
    local proc="${result##*|}"

    if [[ "$title" != "$expected_title" ]]; then
        echo -e "  ${YELLOW}WARN${NC}  ${label}  pane title='${title}' (expected '${expected_title}')"
        FAIL=1
    fi

    if [[ "$proc" == "python3" || "$proc" == "python" ]]; then
        echo -e "  ${GREEN} UP ${NC}  ${label}  (pid running python3)"
    else
        echo -e "  ${RED}DEAD${NC}  ${label}  (pane exists but cmd='${proc}', not python3 — process crashed?)"
        FAIL=1
    fi
}

check_neptune() {
    local prefix="$1"  # empty string for local, "ssh neptune " for remote

    echo -e "${CYAN}── neptune (session: stcp) ──${NC}"

    # check session exists at all
    local session_exists
    session_exists=$(eval "${prefix}tmux has-session -t stcp 2>/dev/null && echo yes || echo no")
    if [[ "$session_exists" == "no" ]]; then
        echo -e "  ${RED}DOWN${NC}  session 'stcp' does not exist"
        echo -e "  ${RED}DOWN${NC}  queue:queue-server"
        echo -e "  ${RED}DOWN${NC}  archive:archive-receiver"
        FAIL=1
        return
    fi

    check_pane "stcp" "queue"   "queue-server"     "queue:queue-server"      "$prefix"
    check_pane "stcp" "archive" "archive-receiver"  "archive:archive-receiver" "$prefix"
}

check_worker() {
    local prefix="$1"

    echo -e "${CYAN}── worker (session: stcp-w) ──${NC}"

    local session_exists
    session_exists=$(eval "${prefix}tmux has-session -t stcp-w 2>/dev/null && echo yes || echo no")
    if [[ "$session_exists" == "no" ]]; then
        echo -e "  ${RED}DOWN${NC}  session 'stcp-w' does not exist"
        echo -e "  ${RED}DOWN${NC}  worker:job-worker"
        echo -e "  ${RED}DOWN${NC}  drain:drain-push"
        FAIL=1
        return
    fi

    check_pane "stcp-w" "worker" "job-worker"  "worker:job-worker"  "$prefix"
    check_pane "stcp-w" "drain"  "drain-push"  "drain:drain-push"   "$prefix"
}

# ── Main ─────────────────────────────────────────────────────
echo -e "${CYAN}═══ health_check.sh ═══${NC}"
echo ""

MODE="${1:-local}"

case "$MODE" in
    neptune)
        check_neptune "ssh neptune "
        ;;
    worker|local)
        check_worker ""
        ;;
    all)
        check_neptune "ssh neptune "
        echo ""
        check_worker ""
        ;;
    *)
        echo "usage: health_check.sh [local|neptune|all]"
        exit 1
        ;;
esac

echo ""
if [[ $FAIL -eq 0 ]]; then
    echo -e "${GREEN}ALL COMPONENTS UP${NC}"
else
    echo -e "${RED}SOME COMPONENTS DOWN — see above${NC}"
fi
exit $FAIL
