# Execution: Job Worker

> Component 3 of 4 — start after neptune queue server is up
> ENFORCES: [RULES.md](RULES.md)

---

## Identity

```
machine:    worker device (behind NAT)
session:    stcp-w
window:     worker
pane title: job-worker
process:    python3 workers/app7/worker.py
connects:   neptune:9999 (TCP, outbound only)
database:   local app7.db (SQLite, path from QUEUE_DBS)
```

## What It Does

Polls the queue server on neptune every `QUEUE_POLL` seconds (default 2s).
When a job arrives, executes the handler and acks the result.

Job handlers:

| Task | What it does |
|------|-------------|
| `ingest_unified_payload` | Parse KMP UnifiedPayload v3/v5, upsert catalog, insert 7 syncable tables |
| `query` | Execute SQL against local app7.db, return rows |
| `ping` | Return `{"pong": true}` |

The ingest handler runs everything in one SQLite transaction. Partial failure
leaves the DB untouched. Uses `INSERT OR IGNORE` keyed on `(device_id, local_id)`
so re-sending a payload is a no-op.

On first start, auto-creates `app7.db` and applies
`dbs/app7/head_schema/schema.sql` if the DB is missing or has missing tables.

Registers with the queue as `<WORKER_NAME>-app7` along with git short hash
as version.

## Environment Variables

All loaded from `.env` via `env.load()`:

| Variable | Default | Required | Notes |
|----------|---------|----------|-------|
| `QUEUE_HOST` | `127.0.0.1` | **YES** | neptune IP |
| `QUEUE_PORT` | `9999` | no | queue server port |
| `QUEUE_POLL` | `2` | no | seconds between polls |
| `QUEUE_DBS` | (hardcoded fallback) | **YES** | format: `app7=/absolute/path/to/app7.db` |
| `WORKER_NAME` | `socket.gethostname()` | **YES** | unique per device, appends `-app7` |

**WORKER_NAME must be unique across devices.** The queue tracks workers by name.
The archive uses it via drain to tag `_source_worker`.

**QUEUE_DBS paths must be absolute.** Relative paths break when cwd changes.

## Prerequisites

- python3 installed
- `.env` file with all required vars
- `workers/app7/worker.py` exists
- `dbs/app7/head_schema/schema.sql` exists (for auto-schema)
- `env.py` exists at repo root
- Queue server on neptune is running and reachable (port 9999 open)
- Network can reach `QUEUE_HOST:QUEUE_PORT` (outbound TCP)

## Deploy Steps

### Fresh start (no session exists)

```bash
cd /home/b/simple-tcp-comm

# Option A: use the start script (creates both worker + drain)
bash auto-docs/deploy/worker_start.sh /home/b/simple-tcp-comm .env

# Option B: manual (worker only)
tmux new-session -d -s stcp-w -n worker -c /home/b/simple-tcp-comm
tmux select-pane -t stcp-w:worker -T job-worker
tmux send-keys -t stcp-w:worker \
  "set -a; source .env; set +a; python3 workers/app7/worker.py" C-m
```

### Restart (pane already exists, process crashed or needs restart)

```bash
tmux send-keys -t stcp-w:worker C-c
sleep 1
tmux send-keys -t stcp-w:worker \
  "set -a; source .env; set +a; python3 workers/app7/worker.py" C-m
```

### Full rebuild (session lost or corrupted)

```bash
cd /home/b/simple-tcp-comm
bash auto-docs/deploy/worker_start.sh /home/b/simple-tcp-comm .env
```

This kills the old `stcp-w` session and rebuilds both windows.

## Verify It's Running

```bash
# Quick: is the pane alive and running python3?
tmux list-panes -t stcp-w:worker -F '#{pane_title} pid=#{pane_pid} cmd=#{pane_current_command}'
# Expected: job-worker pid=<N> cmd=python3

# Functional: is the worker registered on the queue?
python3 client.py workers
# Expected: shows your WORKER_NAME-app7 with recent last_seen timestamp

# Database: does app7.db exist?
ls -la $(grep QUEUE_DBS .env | cut -d= -f3)
# Expected: file exists with non-zero size
```

## Logs

Attach to the pane and read stdout:

```bash
tmux attach -t stcp-w:worker
```

Normal output (idle, no jobs):

```
worker bernardo-pc-app7 (v=7173ee8) polling 137.184.225.153:9999 every 2s
  db app7 ok (16 tables)
  poll → no jobs
  poll → no jobs
```

Normal output (processing a job):

```
  poll → job 42 (ingest_unified_payload)
  app7: ingesting unified payload v3 from sdk_gphone64_x86_64
    catalog: 3 comics, 8 chapters, 26 pages, 13 images
    session_events: 30 inserted, 0 skipped
    annotation_records: 12 inserted, 0 skipped
  ack job=42 ok (234ms)
```

## Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `connection refused` on poll | queue server down or firewall | verify neptune `stcp:queue` is up |
| `timed out` on poll | network issue or neptune overloaded | check connectivity: `nc -zv <QUEUE_HOST> 9999` |
| pane shows `bash` not `python3` | process crashed | check scrollback for traceback, restart |
| `QUEUE_DBS not set` | `.env` not sourced | ensure `set -a; source .env; set +a` before running |
| `missing tables, recreating db` | first start or schema mismatch | normal — schema applied automatically |
| `schema file not found` | `dbs/app7/head_schema/schema.sql` missing | check repo structure |
| SIGTERM graceful shutdown | `Ctrl-C` or process kill | worker finishes current job then exits |

## Graceful Shutdown

The worker handles `SIGINT` and `SIGTERM`. On first signal, it finishes the
current job and exits cleanly. On second signal, it exits immediately.

```bash
# Graceful (finish current job):
tmux send-keys -t stcp-w:worker C-c

# Force (interrupt mid-job — DB transaction rolls back):
tmux send-keys -t stcp-w:worker C-c
tmux send-keys -t stcp-w:worker C-c
```

## Dependencies

```
queue server (neptune:9999) ──► job worker ──► app7.db (local)
  must be up first              (this)         writes here
                                                 │
                                drain reads this ─┘
```

**Queue server must be running. The worker does not depend on the archive
receiver — it only talks to the queue. The drain process (separate component)
reads the DB that this worker writes to.**
