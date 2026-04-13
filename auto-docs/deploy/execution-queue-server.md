# Execution: Queue Server

> Component 1 of 4 — MUST START FIRST
> ENFORCES: [RULES.md](RULES.md)

---

## Identity

```
machine:    neptune (Digital Ocean)
session:    stcp
window:     queue
pane title: queue-server
process:    python3 server.py
port:       :9999 (TCP, 4-byte len + JSON)
database:   jobs.db (SQLite, same directory as server.py)
```

## What It Does

Accepts TCP connections on `:9999`. Clients and workers speak JSON-RPC framed
with a 4-byte big-endian length prefix. Stores jobs in `jobs.db` (SQLite).

Operations: `submit`, `poll`, `ack`, `status`, `list`, `delete`, `reset`, `workers`.

Workers connect to poll for jobs. The app (or client.py) submits jobs.
The queue is FIFO — no routing, no affinity.

## Environment Variables

| Variable | Default | Required | Notes |
|----------|---------|----------|-------|
| `QUEUE_DB` | `jobs.db` | no | SQLite file for job storage |
| `QUEUE_PORT` | `9999` | no | also accepts `sys.argv[1]` |

Neptune runs with defaults — no `.env` file needed for this component.

## Prerequisites

- python3 installed
- `server.py` exists in repo root
- `env.py` exists in repo root (loaded at import time)
- Port 9999 open in DO firewall for all worker IPs
- No other process on `:9999`

## Deploy Steps

### Fresh start (no session exists)

```bash
ssh neptune
cd /root/simple-tcp-comm

# Option A: use the start script (creates both queue + archive)
bash auto-docs/deploy/neptune_start.sh

# Option B: manual (queue only)
tmux new-session -d -s stcp -n queue -c /root/simple-tcp-comm
tmux select-pane -t stcp:queue -T queue-server
tmux send-keys -t stcp:queue "python3 server.py" C-m
```

### Restart (pane already exists, process crashed or needs restart)

```bash
tmux send-keys -t stcp:queue C-c
sleep 1
tmux send-keys -t stcp:queue "python3 server.py" C-m
```

### Full rebuild (session lost or corrupted)

```bash
ssh neptune
cd /root/simple-tcp-comm
bash auto-docs/deploy/neptune_start.sh
```

This kills the old `stcp` session and rebuilds both windows.

## Verify It's Running

```bash
# Quick: is the pane alive and running python3?
tmux list-panes -t stcp:queue -F '#{pane_title} pid=#{pane_pid} cmd=#{pane_current_command}'
# Expected: queue-server pid=<N> cmd=python3

# Process-level: is anything listening on 9999?
ss -tlnp | grep 9999
# Expected: LISTEN ... *:9999 ... python3

# Functional: can a client reach it?
python3 client.py workers
# Expected: {"ok": true, "workers": [...]}
```

## Logs

Attach to the pane and read stdout:

```bash
tmux attach -t stcp:queue
```

Normal output looks like:

```
14:32:01 ← poll     worker=bernardo-pc-app7  ip=...
14:32:01 → poll     no jobs
14:32:05 ← submit   payload={"task":"ingest_unified_payload",...}
14:32:05 → submit   id=42
14:32:07 ← poll     worker=bernardo-pc-app7  ip=...
14:32:07 → poll     job=42
14:32:08 ← ack      job=42 ok
```

## Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Address already in use` | another process on :9999 | `ss -tlnp \| grep 9999`, kill it |
| pane shows `bash` not `python3` | process crashed | check scrollback for traceback, restart |
| workers log `connection refused` | server not running or firewall | verify server is up, check DO firewall |
| `jobs.db` locked | zombie process holding lock | find and kill: `fuser jobs.db` |

## Dependencies

```
NOTHING depends on ──► queue server ──► workers depend on this
                                      ──► client.py depends on this
```

**This component has no upstream dependencies. It must start before
workers or clients connect. Starting workers before the queue =
`connection refused` in worker logs.**
