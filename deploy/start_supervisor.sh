#!/usr/bin/env bash
# start_supervisor.sh — launch supervisor.sh in a named tmux session.
#
# Usage (run from repo root):
#   deploy/start_supervisor.sh [session-name]
#
# Reattach later:
#   tmux attach -t worker-supervisor

set -euo pipefail

SESSION="${1:-worker-supervisor}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "session '$SESSION' already running — attach with: tmux attach -t $SESSION"
    exit 0
fi

tmux new-session -d -s "$SESSION" -c "$REPO_DIR"
tmux send-keys -t "$SESSION" "$SCRIPT_DIR/supervisor.sh" Enter
echo "started supervisor in tmux session '$SESSION'"
echo "  attach:  tmux attach -t $SESSION"
echo "  kill:    tmux kill-session -t $SESSION"
