# Deploy Archive Receiver on Server via tmux send-keys

> THESE RULES MUST BE ENFORCED
> Verified 2026-04-13. All commands via `tmux send-keys` to named panes.

---

## Context

The archive receiver is a TCP server that accepts data pushes from worker drain
processes. It runs on the server (neptune or any reachable host), listens on a
port, and writes into an archive SQLite DB with `INSERT OR IGNORE` deduplication.

There are **3 serialization variants** — the receiver and drain must use the
same one. You choose at deploy time. All three write to the same `archive_schema.sql`
so the archive DB is compatible across variants.

**This doc covers the SERVER side (receiver). For the WORKER side (drain),
see [execution-archive-drain-tmux.md](execution-archive-drain-tmux.md).**

---

## The 3 Variants — CHOOSE ONE

| # | Variant | Flag | Wire format | Deps | When to use |
|---|---------|------|-------------|------|-------------|
| 1 | `json_plain` | `0x00` | raw JSON `{"cols":[],"rows":[[]]}` | stdlib only | Debugging, readable on wire |
| 2 | **`json_zlib`** | `0x01` | zlib(JSON) — 3-6x smaller | stdlib only | **RECOMMENDED — production default** |
| 3 | `struct_pack` | `0x02` | fixed-width binary per table | stdlib only | Maximum throughput, rigid schema |

### Decision guide

```
Is this a debug/test run where you want to inspect raw payloads?
  YES → Variant 1 (json_plain)
  NO  ↓

Is the bottleneck serialization CPU at 10K+ concurrent users?
  YES → Variant 3 (struct_pack)
  NO  → Variant 2 (json_zlib) ← start here
```

### Variant tradeoffs

**json_plain (0x00)** — simplest, zero overhead, largest on wire.
Good for local testing where bandwidth is free. Payload is human-readable
JSON if you tcpdump the connection.

**json_zlib (0x01)** — same JSON format but zlib-compressed before sending.
4-5x smaller on the wire over internet links. Stdlib `zlib.compress/decompress`.
Negligible CPU cost at typical batch sizes (500-5000 rows). Use this unless
you have a reason not to.

**struct_pack (0x02)** — each table has a fixed binary struct format defined in
`archive_receiver/struct_pack/schema_registry.py`. Zero parsing — just
`struct.unpack`. But rigid: string fields are fixed-width (32-128 bytes).
Strings exceeding the width get silently truncated, which can cause UNIQUE
collisions. Adding a column requires updating `schema_registry.py` on both
receiver and drain. Only use if JSON serialization is a measured bottleneck.

---

## Identity

```
machine:    server (neptune or any reachable host)
session:    per deployment — see naming below
pane title: receiver-YYYYMMDD
process:    python3 archive_receiver/<variant>/receiver.py
port:       :8080 (TCP, binary 16-byte header protocol)
database:   archive.db (SQLite, path via ARCHIVE_DB)
```

## Environment Variables

| Variable | Default | Required | Notes |
|----------|---------|----------|-------|
| `ARCHIVE_DB` | `/tmp/archive-receiver-test.db` | **YES** | absolute path, partition needs >100MB free |
| `ARCHIVE_PORT` | `8080` | no | TCP listen port |

**The default ARCHIVE_DB is `/tmp/...` — always override in production.**

## Prerequisites

- python3 installed
- Repo cloned (archive_receiver/ tree must exist)
- `archive_schema.sql` exists in repo root (auto-applied on first start)
- Port open for drain connections (firewall)
- No other process on the chosen port
- Disk partition for ARCHIVE_DB has >100 MB free

## Admission Control (automatic, no config needed)

The receiver enforces these limits internally:

| Condition | Response | Drain behavior |
|-----------|----------|----------------|
| Disk free < 100 MB | `REJECT disk_full` | Drain stops cycle, retries next interval |
| Another insert active | `REJECT busy` | Drain stops cycle, retries next interval |
| Payload > 10 MB | `SHRINK max_rows=1000` | Drain resends with fewer rows |
| Row count > 10,000 | `SHRINK max_rows=5000` | Drain resends with fewer rows |
| Insert took > 2s | Halves suggested batch | Drain adapts next batch |
| Insert took < 200ms | Doubles suggested batch | Drain adapts next batch |

---

## Deploy Steps

### Finding your pane

```bash
tmux list-panes -a -F '#{pane_id} #{pane_title}' | grep receiver
```

### Variables (set these first)

```bash
PANE="%XX"                                                      # your tmux pane ID
TS=20260413                                                     # timestamp tag
REPO="/home/b/simple-tcp-comm-worker-${TS}"                     # git clone path
ARCHIVE_DB="${REPO}/dbs/archive.db"                             # where archive lives
PORT=8080                                                       # listen port
```

---

### Variant 1: json_plain (flags=0x00)

```bash
tmux send-keys -t ${PANE} "ARCHIVE_DB=${ARCHIVE_DB} ARCHIVE_PORT=${PORT} \
  python3 ${REPO}/archive_receiver/json_plain/receiver.py" C-m
```

### Variant 2: json_zlib (flags=0x01) — RECOMMENDED

```bash
tmux send-keys -t ${PANE} "ARCHIVE_DB=${ARCHIVE_DB} ARCHIVE_PORT=${PORT} \
  python3 ${REPO}/archive_receiver/json_zlib/receiver.py" C-m
```

### Variant 3: struct_pack (flags=0x02)

```bash
tmux send-keys -t ${PANE} "ARCHIVE_DB=${ARCHIVE_DB} ARCHIVE_PORT=${PORT} \
  python3 ${REPO}/archive_receiver/struct_pack/receiver.py" C-m
```

---

## Adapting for Neptune (DO droplet)

```bash
DO_SSH="sshpass -p $(head -1 /home/b/dopass) ssh -o StrictHostKeyChecking=accept-new root@137.184.225.153"

# Clone or update repo
${DO_SSH} "
  if [ -d /root/simple-tcp-comm ]; then
    cd /root/simple-tcp-comm && git pull
  else
    git clone https://github.com/berstearns/simple-tcp-comm.git /root/simple-tcp-comm
  fi
"

# Create tmux pane and start receiver
${DO_SSH} "
  tmux new-window -t queue -n archive 2>/dev/null || true
  tmux send-keys -t queue:archive 'cd /root/simple-tcp-comm && ARCHIVE_DB=/data/archive.db python3 archive_receiver/json_zlib/receiver.py' C-m
"
```

## Adapting for Local Testing

Both receiver and drain on the same machine:

```bash
ARCHIVE_DB=/tmp/test-archive.db ARCHIVE_PORT=8080 \
  python3 archive_receiver/json_zlib/receiver.py
```

---

## Verify It's Running

```bash
# Pane alive and python3 running?
tmux list-panes -t ${PANE} -F '#{pane_title} cmd=#{pane_current_command}'

# Port listening?
ss -tlnp | grep ${PORT}

# Archive DB created with tables?
sqlite3 ${ARCHIVE_DB} ".tables"
# Expected: 17 tables

# Disk space ok?
df -h $(dirname ${ARCHIVE_DB})
# Must be >100MB free
```

## Expected Output

Startup:

```
variant: json_zlib (flags=0x01)
archive receiver on :8080 (archive=/home/b/simple-tcp-comm-worker-20260413/dbs/archive.db)
```

Accepting data:

```
  OK table=comics rows=3 inserted=3 skipped=0 ms=12
  OK table=chapters rows=8 inserted=8 skipped=0 ms=15
  OK table=session_events rows=30 inserted=22 skipped=8 ms=45
```

Rejecting:

```
  REJECT busy table=pages rows=26 bytes=4096
  REJECT disk_full table=session_events rows=500 bytes=98304
  SHRINK table=page_interactions rows=15000 bytes=12000000
```

## Switching Variants

All variants write to the same archive DB using the same schema. You can:

1. `Ctrl-C` in the receiver pane to stop
2. Start a different variant in the same pane
3. The archive keeps all previously inserted data — no reset needed

**The drain on the worker side must switch to the matching variant at the
same time. Mismatched variants = garbled data / deserialization errors.**

## Stopping

`Ctrl-C` in the pane. The receiver handles `KeyboardInterrupt` cleanly.

## Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Address already in use` | another process on port | `ss -tlnp \| grep <port>`, kill it |
| pane shows `bash`/`zsh` not `python3` | process crashed | check scrollback for traceback, restart |
| drain logs `connection refused` | receiver not running or firewall | verify receiver is up, check firewall |
| all drains get `REJECT busy` | insert taking too long | check disk I/O, archive.db WAL size |
| all drains get `REJECT disk_full` | <100MB free | free space or move ARCHIVE_DB |
| `archive_schema.sql` not found | repo structure broken | verify file at repo root |
| struct_pack garbled data | variant mismatch | ensure receiver and drain use same variant |

## Naming Convention — THESE RULES MUST BE ENFORCED

| Resource | Name |
|----------|------|
| tmux pane title | `receiver-YYYYMMDD` |
| Archive DB | `<repo>/dbs/archive.db` |
| Log identification | receiver prints variant and port on startup |

## Dependencies

```
queue server (:9999)   ← should be up first (convention)
       ↓
archive receiver (:8080)  ← THIS COMPONENT
       ↑
drain processes connect here (from worker machines)
```

**The receiver does not depend on the queue server at the protocol level.
But by convention it starts second. Drain processes get `connection refused`
if this is not running.**
