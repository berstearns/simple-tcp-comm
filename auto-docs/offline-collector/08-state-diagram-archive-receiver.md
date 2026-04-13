# State Diagram — Full Pipeline with Archive Receiver

> Auto-generated: 2026-04-13

## System Overview

Two independent TCP paths. Workers initiate both (outbound only — NAT-safe).

```
                    ┌─────────────────────────────────────────────────────────┐
                    │            NEPTUNE  (Digital Ocean)                     │
                    │                                                         │
                    │   ┌─────────────────────┐  ┌─────────────────────────┐  │
                    │   │  server.py  :9999    │  │  receiver.py  :8080     │  │
                    │   │  TCP Job Queue       │  │  Archive Receiver       │  │
                    │   │                     │  │                         │  │
                    │   │  ┌───────┐ ┌──────┐ │  │  ┌───────────────────┐  │  │
                    │   │  │jobs.db│ │workers│ │  │  │   archive.db     │  │  │
                    │   │  └───────┘ └──────┘ │  │  │   (17 tables)    │  │  │
                    │   └─────────────────────┘  │  └───────────────────┘  │  │
                    │            ▲                │           ▲             │  │
                    └────────────┼────────────────┼───────────┼─────────────┘  │
                                │                            │                │
                           TCP :9999                    TCP :8080              │
                           JSON-RPC                     binary protocol       │
                           [4B len][JSON]               [16B hdr][verdict]    │
                                │                       [payload][receipt]     │
                   ┌────────────┼────────────────────────────┼────────────┐
                   │            │                            │            │
                   ▼            │                            │            ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                         WORKER DEVICE  (behind NAT)                        │
 │                                                                             │
 │   ┌─────────────────────────┐         ┌──────────────────────────────────┐  │
 │   │  worker.py              │         │  drain.py                        │  │
 │   │                         │         │                                  │  │
 │   │  poll ──► exec ──► ack  │         │  read worker DB (read-only)     │  │
 │   │  loop every 2s          │         │  serialize → send to :8080       │  │
 │   │                         │         │  loop every 300s                 │  │
 │   └───────────┬─────────────┘         └────────────┬─────────────────────┘  │
 │               │                                    │                        │
 │               ▼                                    │                        │
 │         ┌───────────┐                              │                        │
 │         │  app7.db  │◄─────────────────────────────┘                        │
 │         │  (worker) │  reads cold rows                                      │
 │         └───────────┘                                                       │
 └─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow — Two Independent Paths

### Path 1: Job Queue (port 9999)

```
  Android App                  neptune                      worker
  ──────────                   ───────                      ──────
       │                          │                            │
       │──── submit payload ────►│                            │
       │     (TCP JSON-RPC)      │   store in jobs.db         │
       │                          │                            │
       │                          │◄──── poll (every 2s) ─────│
       │                          │                            │
       │                          │───── job payload ────────►│
       │                          │                            │  exec handler
       │                          │                            │  INSERT into app7.db
       │                          │◄──── ack (result) ────────│
       │                          │                            │
```

### Path 2: Archive Drain (port 8080)

```
  drain.py (on worker)                    receiver.py (on neptune)
  ────────────────────                    ────────────────────────
       │                                           │
       │──── HEADER (16 bytes) ──────────────────►│
       │     payload_size, row_count, table_id,    │
       │     flags, worker_hash                    │
       │                                           │  admission control:
       │                                           │    disk space?
       │                                           │    already inserting?
       │                                           │    payload too big?
       │                                           │
       │◄──── VERDICT (12 bytes) ─────────────────│
       │      status: ACCEPT / REJECT / SHRINK     │
       │      reason: ok / busy / disk_full        │
       │      max_rows, max_bytes                  │
       │                                           │
       │  [only if ACCEPT]                         │
       │                                           │
       │──── PAYLOAD (N bytes) ──────────────────►│
       │     (json / json+zlib / struct_pack)      │
       │                                           │  INSERT OR IGNORE
       │                                           │  into archive.db
       │                                           │
       │◄──── RECEIPT (12 bytes) ─────────────────│
       │      inserted, skipped, next_max_rows     │
       │                                           │
       │  [adapt batch_rows for next table]        │
       │                                           │
```

## Component State Matrix

```
 ┌──────────────────┬───────────┬───────────┬──────────────────────────────────┐
 │   Component      │  Machine  │   Port    │  State                           │
 ├──────────────────┼───────────┼───────────┼──────────────────────────────────┤
 │ server.py        │ neptune   │ :9999     │ always running, accepts JSON-RPC │
 │ receiver.py      │ neptune   │ :8080     │ always running, binary protocol  │
 │ worker.py        │ worker    │ (client)  │ polls :9999 every 2s             │
 │ drain.py         │ worker    │ (client)  │ pushes to :8080 every 300s       │
 └──────────────────┴───────────┴───────────┴──────────────────────────────────┘
```

## Serialization Variants (pick one per worker)

```
 ┌─────────────┬────────┬──────────────────────────────────┬─────────────┐
 │ Variant     │ Flag   │ Wire format                      │ Tradeoff    │
 ├─────────────┼────────┼──────────────────────────────────┼─────────────┤
 │ json_plain  │ 0x00   │ raw JSON {"cols":[],"rows":[[]]} │ debuggable  │
 │ json_zlib   │ 0x01   │ zlib(JSON)  — 3-6x smaller       │ recommended │
 │ struct_pack │ 0x02   │ fixed-width binary structs        │ fastest     │
 └─────────────┴────────┴──────────────────────────────────┴─────────────┘
```

---

## Deployment

**All deployment rules, startup scripts, and health checks live in
[`auto-docs/deploy/`](../deploy/). Those rules must be enforced.**

See:
- [`auto-docs/deploy/RULES.md`](../deploy/RULES.md) — strict naming conventions (session, window, pane)
- [`auto-docs/deploy/neptune_start.sh`](../deploy/neptune_start.sh) — bootstrap neptune
- [`auto-docs/deploy/worker_start.sh`](../deploy/worker_start.sh) — bootstrap each worker
- [`auto-docs/deploy/health_check.sh`](../deploy/health_check.sh) — verify everything is alive

Quick reference:

```
 NEPTUNE  session=stcp              WORKER  session=stcp-w
 ├── queue:queue-server             ├── worker:job-worker
 │   server.py :9999                │   workers/app7/worker.py → :9999
 └── archive:archive-receiver       └── drain:drain-push
     receiver.py :8080                  drain.py → :8080
```
