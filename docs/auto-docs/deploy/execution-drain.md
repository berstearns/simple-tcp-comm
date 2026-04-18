# Execution: Drain

> Component 4 of 4 — start last, after queue + receiver + worker are up
> ENFORCES: [RULES.md](RULES.md)

---

## Identity

```
machine:    worker device (behind NAT)
session:    stcp-w
window:     drain
pane title: drain-push
process:    python3 archive_receiver/json_zlib/drain.py
connects:   neptune:8080 (TCP, outbound only)
reads:      local app7.db (read-only, same file the job worker writes)
variant:    json_zlib (flags=0x01, must match receiver variant)
```

## What It Does

Every `DRAIN_INTERVAL` seconds (default 300 = 5 minutes), opens the local
worker DB in read-only mode and iterates over all 16 tables. For each table
with rows, opens a fresh TCP connection to the archive receiver and runs the
4-phase binary handshake:

```
1. Send HEADER (16 bytes) → payload_size, row_count, table_id, flags, worker_hash
2. Recv VERDICT (12 bytes) → ACCEPT / REJECT / SHRINK
3. Send PAYLOAD (N bytes)  → zlib(JSON{"cols":[],"rows":[]})   [only if ACCEPT]
4. Recv RECEIPT (12 bytes) → inserted, skipped, next_max_rows
```

Batch size starts at 500 rows and adapts based on receiver feedback
(`next_max_rows` in RECEIPT). If the receiver is slow (insert >2s), it halves.
If fast (<200ms), it doubles up to 10000.

For watermarked tables (11 tables with integer PKs), fetches `LIMIT batch_rows`
ordered by `id`. For catalog tables (5 tables), fetches all rows (small, static).

If the receiver is unreachable or rejects, the drain stops the current cycle
and retries on the next interval. No data is lost — the worker DB is the
source of truth and the drain only reads it.

## Environment Variables

| Variable | Default | Required | Notes |
|----------|---------|----------|-------|
| `WORKER_DB` | (empty → exits) | **YES** | absolute path to worker's app7.db |
| `ARCHIVE_HOST` | `127.0.0.1` | **YES** | neptune IP |
| `ARCHIVE_PORT` | `8080` | no | archive receiver port |
| `WORKER_NAME` | `drain-worker` | **YES** | must match the job worker's name |
| `DRAIN_INTERVAL` | `300` | no | seconds between drain cycles |
| `COLD_AGE_MS` | `3600000` | no | cold row threshold (1 hour, not currently used in loop) |

**WORKER_DB must point to the same file the job worker writes to.**
The drain opens it read-only (`file:...?mode=ro`).

**WORKER_NAME must be unique per device.** The receiver hashes it to 2 bytes
and tags archived rows as `worker-<hash>`. If two devices share a name, their
data gets mixed in the archive.

**ARCHIVE_HOST must point to neptune.** The drain does NOT read this from
`.env` automatically — it's passed inline at startup by the `worker_start.sh`
script using `QUEUE_HOST` from `.env`.

## Prerequisites

- python3 installed
- `archive_receiver/json_zlib/drain.py` exists
- `archive_receiver/drain_base.py` exists
- `archive_receiver/protocol.py` exists
- Worker's `app7.db` exists and has tables (job worker must have started at least once)
- Archive receiver on neptune is running and reachable (port 8080 open)
- Network can reach `ARCHIVE_HOST:ARCHIVE_PORT` (outbound TCP)

## Deploy Steps

### Fresh start (no session exists)

```bash
cd /home/b/simple-tcp-comm

# Option A: use the start script (creates both worker + drain)
bash auto-docs/deploy/worker_start.sh /home/b/simple-tcp-comm .env

# Option B: manual (drain only, assuming stcp-w session exists)
# First extract the DB path from .env:
DB_PATH=$(grep QUEUE_DBS .env | cut -d= -f2 | cut -d= -f2)
QUEUE_HOST=$(grep QUEUE_HOST .env | cut -d= -f2)
WORKER_NAME=$(grep WORKER_NAME .env | cut -d= -f2)

tmux new-window -t stcp-w -n drain -c /home/b/simple-tcp-comm
tmux select-pane -t stcp-w:drain -T drain-push
tmux send-keys -t stcp-w:drain \
  "WORKER_DB=${DB_PATH} ARCHIVE_HOST=${QUEUE_HOST} ARCHIVE_PORT=8080 WORKER_NAME=${WORKER_NAME} python3 archive_receiver/json_zlib/drain.py" C-m
```

### Restart (pane already exists, process crashed or needs restart)

```bash
tmux send-keys -t stcp-w:drain C-c
sleep 1
tmux send-keys -t stcp-w:drain \
  "WORKER_DB=<path> ARCHIVE_HOST=<host> ARCHIVE_PORT=8080 WORKER_NAME=<name> python3 archive_receiver/json_zlib/drain.py" C-m
```

**Replace `<path>`, `<host>`, `<name>` with actual values.** Or rebuild:

```bash
bash auto-docs/deploy/worker_start.sh /home/b/simple-tcp-comm .env
```

### One-shot mode (drain once, don't loop)

For testing or manual runs:

```bash
WORKER_DB=/path/to/app7.db \
  ARCHIVE_HOST=137.184.225.153 \
  ARCHIVE_PORT=8080 \
  WORKER_NAME=bernardo-pc \
  python3 archive_receiver/json_zlib/drain.py --once
```

### Full rebuild (session lost or corrupted)

```bash
cd /home/b/simple-tcp-comm
bash auto-docs/deploy/worker_start.sh /home/b/simple-tcp-comm .env
```

### Switching serialization variant

Replace `json_zlib` with another variant. **Must match the receiver on neptune.**

```bash
# json_plain (flags=0x00)
python3 archive_receiver/json_plain/drain.py

# struct_pack (flags=0x02)
python3 archive_receiver/struct_pack/drain.py
```

## Verify It's Running

```bash
# Quick: is the pane alive and running python3?
tmux list-panes -t stcp-w:drain -F '#{pane_title} pid=#{pane_pid} cmd=#{pane_current_command}'
# Expected: drain-push pid=<N> cmd=python3

# Is it sleeping between cycles? (normal — it sleeps DRAIN_INTERVAL seconds)
# Attach and check last log line:
tmux capture-pane -t stcp-w:drain -p | tail -5
# Expected: "sleeping 300s..." or "--- drain cycle HH:MM:SS ---"
```

## Logs

Attach to the pane and read stdout:

```bash
tmux attach -t stcp-w:drain
```

Normal output (successful cycle):

```
--- drain cycle 14:35:00 (batch_rows=500) ---
  comics: sent=3 inserted=0 skipped=3 next_batch=500
  chapters: sent=8 inserted=0 skipped=8 next_batch=500
  session_events: sent=30 inserted=12 skipped=18 next_batch=1000
  total sent this cycle: 12
  sleeping 300s...
```

Receiver unavailable:

```
--- drain cycle 14:40:00 (batch_rows=500) ---
  comics: receiver unavailable, stopping cycle
  total sent this cycle: 0
  sleeping 300s...
```

Receiver busy:

```
  session_events:
    REJECTED (busy)
```

Receiver asks to shrink:

```
  page_interactions:
    SHRINK → max_rows=1000 max_bytes=5000000
  page_interactions: shrink requested, new batch_rows=1000
```

## Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `WORKER_DB not set` | env var missing at startup | pass inline or fix launch command |
| `connection refused` to :8080 | archive receiver down or firewall | verify neptune `stcp:archive` is up |
| `receiver unavailable, stopping cycle` | receiver down or network glitch | transient — retries next cycle |
| `REJECTED (busy)` | receiver is mid-insert from another drain | transient — retries next cycle |
| `REJECTED (disk_full)` | neptune disk <100MB free | free space on neptune |
| pane shows `bash` not `python3` | process crashed | check scrollback for traceback, restart |
| all rows `skipped=N inserted=0` | data already in archive | normal — idempotent, no duplicates |
| `timed out` | network or receiver hung | check connectivity: `nc -zv <HOST> 8080` |

## Data Flow

```
app7.db (worker) ──read-only──► drain ──TCP:8080──► receiver ──► archive.db
       ▲                                                    
       │                                                    
  job worker writes here                                    
```

**The drain never modifies app7.db.** It opens with `?mode=ro`.
If the archive receiver is down, the drain logs the error and sleeps until
the next cycle. No data is lost because the worker DB is the persistent
source of truth.

## Dependencies

```
archive receiver (neptune:8080) ──► drain ──► reads worker's app7.db
  must be up                       (this)     must exist with tables
                                                    │
                                 job worker writes ──┘
```

**The drain is the last component in the startup chain. It depends on:**
1. **Archive receiver** on neptune (to accept connections)
2. **Worker's app7.db** (to have data to drain)

**If the receiver is down, the drain degrades gracefully** — it logs
`receiver unavailable` and retries on the next cycle. No crash, no data loss.
