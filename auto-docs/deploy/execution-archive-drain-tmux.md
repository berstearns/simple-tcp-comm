# Deploy Archive Drain on Worker via tmux send-keys

> THESE RULES MUST BE ENFORCED
> Verified 2026-04-13. All commands via `tmux send-keys` to named panes.

---

## Context

The archive drain runs on the **worker machine** alongside the job worker.
Every `DRAIN_INTERVAL` seconds (default 300s = 5 min), it opens the worker's
`app7.db` in read-only mode, iterates all 16 tables, and pushes each batch to
the archive receiver via TCP.

There are **3 serialization variants** — the drain and receiver must use the
same one. You choose at deploy time.

**This doc covers the WORKER side (drain). For the SERVER side (receiver),
see [execution-archive-receiver-tmux.md](execution-archive-receiver-tmux.md).**

---

## The 3 Variants — MUST MATCH THE RECEIVER

| # | Variant | Flag | Drain file | Receiver file |
|---|---------|------|-----------|---------------|
| 1 | `json_plain` | `0x00` | `archive_receiver/json_plain/drain.py` | `archive_receiver/json_plain/receiver.py` |
| 2 | **`json_zlib`** | `0x01` | `archive_receiver/json_zlib/drain.py` | `archive_receiver/json_zlib/receiver.py` |
| 3 | `struct_pack` | `0x02` | `archive_receiver/struct_pack/drain.py` | `archive_receiver/struct_pack/receiver.py` |

**If the drain uses `json_zlib` but the receiver is running `json_plain`,
the receiver will fail to deserialize. Always deploy matching pairs.**

---

## Identity

```
machine:    worker device (behind NAT, outbound only)
session:    per deployment — see naming below
pane title: drain-YYYYMMDD
process:    python3 archive_receiver/<variant>/drain.py
connects:   <ARCHIVE_HOST>:<ARCHIVE_PORT> (TCP, outbound)
reads:      worker's app7.db (read-only, same file the job worker writes)
```

## Environment Variables

| Variable | Default | Required | Notes |
|----------|---------|----------|-------|
| `WORKER_DB` | (empty → exits) | **YES** | absolute path to worker's app7.db |
| `ARCHIVE_HOST` | `127.0.0.1` | **YES** | IP of the archive receiver |
| `ARCHIVE_PORT` | `8080` | no | port of the archive receiver |
| `WORKER_NAME` | `drain-worker` | **YES** | unique per device — hashed to 2 bytes for `_source_worker` |
| `DRAIN_INTERVAL` | `300` | no | seconds between drain cycles |
| `COLD_AGE_MS` | `3600000` | no | cold row threshold in ms (1 hour) |

**WORKER_DB must point to the same file the job worker writes to.**
The drain opens it read-only (`file:...?mode=ro`). It never modifies app7.db.

**WORKER_NAME must be unique per device.** Two devices sharing a name →
their data gets mixed in the archive under the same `_source_worker` hash.

## Prerequisites

- python3 installed
- Repo cloned (archive_receiver/ tree must exist)
- Worker's `app7.db` exists and has tables (job worker must have run at least once)
- Archive receiver running and reachable at `ARCHIVE_HOST:ARCHIVE_PORT`
- Network can reach the receiver (outbound TCP, NAT-safe)

---

## Deploy Steps

### Finding your pane

```bash
tmux list-panes -a -F '#{pane_id} #{pane_title}' | grep drain
```

### Variables (set these first)

```bash
PANE="%YY"                                                      # your tmux pane ID
TS=20260413                                                     # matches worker timestamp
REPO="/home/b/simple-tcp-comm-worker-${TS}"                     # git clone path
WORKER_DB="${REPO}/dbs/app7.db"                                 # worker DB to drain
WORKER_NAME="worker-${TS}"                                     # unique identifier
ARCHIVE_HOST="137.184.225.153"                                  # receiver IP (neptune)
ARCHIVE_PORT=8080                                               # receiver port
DRAIN_INTERVAL=60                                               # seconds between cycles
```

---

### Variant 1: json_plain (flags=0x00)

```bash
tmux send-keys -t ${PANE} "WORKER_DB=${WORKER_DB} WORKER_NAME=${WORKER_NAME} \
  ARCHIVE_HOST=${ARCHIVE_HOST} ARCHIVE_PORT=${ARCHIVE_PORT} \
  DRAIN_INTERVAL=${DRAIN_INTERVAL} \
  python3 ${REPO}/archive_receiver/json_plain/drain.py" C-m
```

### Variant 2: json_zlib (flags=0x01) — RECOMMENDED

```bash
tmux send-keys -t ${PANE} "WORKER_DB=${WORKER_DB} WORKER_NAME=${WORKER_NAME} \
  ARCHIVE_HOST=${ARCHIVE_HOST} ARCHIVE_PORT=${ARCHIVE_PORT} \
  DRAIN_INTERVAL=${DRAIN_INTERVAL} \
  python3 ${REPO}/archive_receiver/json_zlib/drain.py" C-m
```

### Variant 3: struct_pack (flags=0x02)

```bash
tmux send-keys -t ${PANE} "WORKER_DB=${WORKER_DB} WORKER_NAME=${WORKER_NAME} \
  ARCHIVE_HOST=${ARCHIVE_HOST} ARCHIVE_PORT=${ARCHIVE_PORT} \
  DRAIN_INTERVAL=${DRAIN_INTERVAL} \
  python3 ${REPO}/archive_receiver/struct_pack/drain.py" C-m
```

---

### One-shot mode (drain once, don't loop)

For testing or manual verification. Append `--once`:

```bash
tmux send-keys -t ${PANE} "WORKER_DB=${WORKER_DB} WORKER_NAME=${WORKER_NAME} \
  ARCHIVE_HOST=${ARCHIVE_HOST} ARCHIVE_PORT=${ARCHIVE_PORT} \
  python3 ${REPO}/archive_receiver/json_zlib/drain.py --once" C-m
```

---

## How the Drain Loop Works

```
1. Open worker app7.db in read-only mode
2. For each of 16 tables:
   a. Check table exists in worker DB
   b. Fetch rows (LIMIT batch_rows for watermarked tables, all for catalog)
   c. Serialize (JSON / zlib / struct_pack based on variant)
   d. Open TCP connection to receiver
   e. Send HEADER (16 bytes): payload_size, row_count, table_id, flags, worker_hash
   f. Recv VERDICT (12 bytes): ACCEPT / REJECT / SHRINK
   g. If ACCEPT: send PAYLOAD, recv RECEIPT (inserted, skipped, next_max_rows)
   h. Adapt batch_rows from receiver feedback
3. Close DB
4. Sleep DRAIN_INTERVAL seconds
5. Repeat
```

Batch size starts at **500 rows** and adapts:
- Receiver insert >2s → halves batch
- Receiver insert <200ms → doubles batch (max 10000)
- Receiver sends `SHRINK` → drain uses the suggested limit

---

## Adapting for Local Testing

Both receiver and drain on the same machine:

```bash
# Terminal 1: receiver
ARCHIVE_DB=/tmp/test-archive.db python3 archive_receiver/json_zlib/receiver.py

# Terminal 2: drain (one-shot)
WORKER_DB=/path/to/app7.db WORKER_NAME=test-worker \
  ARCHIVE_HOST=127.0.0.1 ARCHIVE_PORT=8080 \
  python3 archive_receiver/json_zlib/drain.py --once
```

## Adapting for a Remote Worker (NAT'd, behind router)

The drain connects **outbound** to the receiver. No inbound port needed on
the worker machine. The receiver must be on a machine with an open port.

```bash
# On worker machine (behind NAT):
WORKER_DB=/root/dbs/app7.db \
WORKER_NAME=atlas-worker \
ARCHIVE_HOST=137.184.225.153 \
ARCHIVE_PORT=8080 \
DRAIN_INTERVAL=300 \
  python3 archive_receiver/json_zlib/drain.py
```

---

## Verify It's Running

```bash
# Pane alive and python3 running?
tmux list-panes -t ${PANE} -F '#{pane_title} cmd=#{pane_current_command}'

# Check last few lines of output:
tmux capture-pane -t ${PANE} -p -S -10

# Is it sleeping between cycles? (normal)
# Last line should be: "sleeping 300s..." or "--- drain cycle HH:MM:SS ---"
```

## Expected Output

Startup:

```
variant: json_zlib (flags=0x01)
```

Successful cycle:

```
--- drain cycle 14:35:00 (batch_rows=500) ---
  comics: sent=3 inserted=0 skipped=3 next_batch=500
  chapters: sent=8 inserted=0 skipped=8 next_batch=500
  session_events: sent=30 inserted=12 skipped=18 next_batch=1000
  page_interactions: sent=54 inserted=54 skipped=0 next_batch=1000
  total sent this cycle: 66
  sleeping 60s...
```

Receiver unavailable:

```
--- drain cycle 14:40:00 (batch_rows=500) ---
  comics: receiver unavailable, stopping cycle
  total sent this cycle: 0
  sleeping 60s...
```

Receiver busy or shrinking:

```
  session_events:
    REJECTED (busy)
  page_interactions:
    SHRINK → max_rows=1000 max_bytes=5000000
  page_interactions: shrink requested, new batch_rows=1000
```

All data already archived (idempotent):

```
  comics: sent=3 inserted=0 skipped=3 next_batch=500
  chapters: sent=8 inserted=0 skipped=8 next_batch=500
  total sent this cycle: 0
```

---

## Switching Variants

1. `Ctrl-C` in the drain pane to stop
2. Start a different variant in the same pane
3. **Switch the receiver to the matching variant at the same time**

Mismatched variants = deserialization errors on the receiver side. The drain
will see `receiver unavailable` because the connection closes mid-handshake.

---

## Stopping

`Ctrl-C` in the pane. The drain finishes the current sleep/batch and exits.

## Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `WORKER_DB not set` | env var missing at startup | pass inline in the command |
| `connection refused` to receiver | receiver not running or firewall | verify receiver is up |
| `receiver unavailable, stopping cycle` | transient network / receiver down | retries next cycle automatically |
| `REJECTED (busy)` | receiver mid-insert from another drain | retries next cycle |
| `REJECTED (disk_full)` | server disk <100MB free | free space on server |
| pane shows `bash`/`zsh` not `python3` | process crashed | check scrollback, restart |
| all rows `skipped=N inserted=0` | data already in archive | normal — idempotent |
| `timed out` | network or receiver hung | `nc -zv <HOST> <PORT>` to test connectivity |
| struct_pack `ValueError: no schema match` | table has extra/different columns | update `schema_registry.py` or use json_zlib |

---

## Naming Convention — THESE RULES MUST BE ENFORCED

| Resource | Name |
|----------|------|
| tmux pane title | `drain-YYYYMMDD` |
| WORKER_NAME | `worker-YYYYMMDD` (must match the job worker's name) |
| Repo path | `~/simple-tcp-comm-worker-YYYYMMDD/` |

## Dependencies

```
archive receiver (server:8080)  ← must be up
       ↑
archive drain (this component)  → reads worker's app7.db
       ↑                                    ↑
job worker writes to app7.db ───────────────┘
```

**The drain is the last component in the startup chain. It depends on:**
1. **Archive receiver** on the server (to accept connections)
2. **Worker's app7.db** (to have data to drain — job worker must have run)

**If the receiver is down, the drain degrades gracefully** — logs
`receiver unavailable` and retries next cycle. No crash, no data loss.
The worker DB is the persistent source of truth.
