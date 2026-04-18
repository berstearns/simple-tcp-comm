# Execution: Archive Receiver

> Component 2 of 4 — start after queue server, before any drain
> ENFORCES: [RULES.md](RULES.md)

---

## Identity

```
machine:    neptune (Digital Ocean)
session:    stcp
window:     archive
pane title: archive-receiver
process:    python3 archive_receiver/json_zlib/receiver.py
port:       :8080 (TCP, binary 16-byte header protocol)
database:   /data/archive.db (SQLite, path via ARCHIVE_DB)
variant:    json_zlib (flags=0x01, recommended)
```

## What It Does

Listens on `:8080` for drain connections from worker devices. Each connection
is one batch for one table. The protocol is a 4-phase binary handshake:

```
drain ──── HEADER (16 bytes) ────────► receiver
           payload_size, row_count,
           table_id, flags, worker_hash

drain ◄──── VERDICT (12 bytes) ──────  receiver
            ACCEPT / REJECT / SHRINK       admission control:
            reason, max_rows, max_bytes      disk free? busy? too big?

drain ──── PAYLOAD (N bytes) ────────► receiver     [only if ACCEPT]
           zlib-compressed JSON

drain ◄──── RECEIPT (12 bytes) ──────  receiver
            inserted, skipped,
            next_max_rows (adaptive)
```

Inserts rows with `INSERT OR IGNORE` on UNIQUE constraints. Idempotent.
Each row gets `_source_worker = "worker-<hash>"` to track origin.

Admission control rejects when:
- Disk free < 100 MB (`REASON_DISK_FULL`)
- Another insert is active (`REASON_BUSY`)
- Payload > 10 MB or rows > 10000 (`SHRINK` with suggested limits)

## Environment Variables

| Variable | Default | Required | Notes |
|----------|---------|----------|-------|
| `ARCHIVE_DB` | `/tmp/archive-receiver-test.db` | **YES** | must be absolute path, partition needs >100MB free |
| `ARCHIVE_PORT` | `8080` | no | TCP listen port |

**The default `ARCHIVE_DB` is `/tmp/...` — always override in production.**

## Prerequisites

- python3 installed
- `archive_receiver/json_zlib/receiver.py` exists
- `archive_receiver/receiver_base.py` exists
- `archive_receiver/protocol.py` exists
- `archive_schema.sql` exists in repo root (auto-applied on first start)
- Port 8080 open in DO firewall for all worker IPs
- No other process on `:8080`
- Disk partition holding `ARCHIVE_DB` has >100 MB free

## Deploy Steps

### Fresh start (no session exists)

```bash
ssh neptune
cd /root/simple-tcp-comm

# Option A: use the start script (creates both queue + archive)
bash auto-docs/deploy/neptune_start.sh /data/archive.db

# Option B: manual (archive only, assuming stcp session exists)
tmux new-window -t stcp -n archive -c /root/simple-tcp-comm
tmux select-pane -t stcp:archive -T archive-receiver
tmux send-keys -t stcp:archive \
  "ARCHIVE_DB=/data/archive.db python3 archive_receiver/json_zlib/receiver.py" C-m
```

### Restart (pane already exists, process crashed or needs restart)

```bash
tmux send-keys -t stcp:archive C-c
sleep 1
tmux send-keys -t stcp:archive \
  "ARCHIVE_DB=/data/archive.db python3 archive_receiver/json_zlib/receiver.py" C-m
```

### Full rebuild (session lost or corrupted)

```bash
ssh neptune
cd /root/simple-tcp-comm
bash auto-docs/deploy/neptune_start.sh /data/archive.db
```

### Switching serialization variant

Replace `json_zlib` with another variant. **Both receiver and drain must match.**

```bash
# json_plain (flags=0x00, debuggable, larger on wire)
ARCHIVE_DB=/data/archive.db python3 archive_receiver/json_plain/receiver.py

# struct_pack (flags=0x02, fastest, fixed-width — may truncate strings)
ARCHIVE_DB=/data/archive.db python3 archive_receiver/struct_pack/receiver.py
```

## Verify It's Running

```bash
# Quick: is the pane alive and running python3?
tmux list-panes -t stcp:archive -F '#{pane_title} pid=#{pane_pid} cmd=#{pane_current_command}'
# Expected: archive-receiver pid=<N> cmd=python3

# Process-level: is anything listening on 8080?
ss -tlnp | grep 8080
# Expected: LISTEN ... *:8080 ... python3

# Database: does archive.db exist and have tables?
sqlite3 /data/archive.db ".tables"
# Expected: 17 tables (comics, chapters, pages, ... collection_log)

# Disk: is there enough free space?
df -h /data/
# Must be >100MB free or receiver rejects all connections
```

## Logs

Attach to the pane and read stdout:

```bash
tmux attach -t stcp:archive
```

Normal output looks like:

```
archive receiver on :8080 (archive=/data/archive.db)
  OK table=comics rows=3 inserted=3 skipped=0 ms=12
  OK table=chapters rows=8 inserted=8 skipped=0 ms=15
  OK table=session_events rows=30 inserted=22 skipped=8 ms=45
```

Rejection output:

```
  REJECT busy table=pages rows=26 bytes=4096
  SHRINK table=session_events rows=15000 bytes=12000000
```

## Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Address already in use` | another process on :8080 | `ss -tlnp \| grep 8080`, kill it |
| pane shows `bash` not `python3` | process crashed | check scrollback for traceback, restart |
| drain logs `connection refused` | receiver not running or firewall | verify receiver is up, check DO firewall |
| all drains get `REJECT busy` | an insert is taking too long | check disk I/O, archive.db size, WAL file |
| all drains get `REJECT disk_full` | partition <100MB free | free space or move ARCHIVE_DB |
| `archive_schema.sql` not found | repo structure broken | verify file exists at repo root |

## Schema Initialization

On first start, receiver reads `archive_schema.sql` from the repo root and
applies it to `ARCHIVE_DB`. This creates 17 tables:

- 4 catalog: `comics`, `chapters`, `pages`, `images`
- 1 audit: `ingest_batches`
- 6 event: `session_events`, `annotation_records`, `chat_messages`,
  `page_interactions`, `app_launch_records`, `settings_changes`
- 1 reference: `region_translations`
- 4 session hierarchy: `app_sessions`, `comic_sessions`, `chapter_sessions`, `page_sessions`
- 1 collection audit: `collection_log`

All data tables have `_archive_id` (auto-increment PK), `_source_worker` (origin),
and a UNIQUE constraint on business keys for idempotent insertion.

## Dependencies

```
queue server ──► archive receiver ──► drain processes depend on this
(should be up)   (this component)
```

**The archive receiver does not depend on the queue server at the protocol
level, but by convention it starts second. Drain processes on workers will
get `connection refused` if this is not running.**
