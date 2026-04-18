# Strategies for Collecting from NAT'd Workers

> From conversation: designing solutions for ephemeral edge workers behind NAT that fill up.

## Constraints

| Constraint | Reality |
|---|---|
| Workers are behind NAT | Can't reach them inbound |
| Workers fill up | Disk is finite, need to offload and prune |
| Workers are not ephemeral | They stay alive, they just get full |
| Queue is the bottleneck | Don't re-route collected data back through it |
| Solo dev, 1000 users | Simple ops, no infrastructure bloat |

## The problem

```
App → Queue → Worker (NAT'd, disk filling up)
                ↓
              HOW does data get OUT
              without going back through the queue?
```

## Strategy dimensions

### A. WHO initiates the transfer?

- **A1. Collector pulls** — collector asks worker for data (current model, needs inbound access)
- **A2. Worker pushes** — worker decides when to export, sends outbound (NAT-friendly)
- **A3. Piggyback on ack** — attach export data to the existing ingest ack

### B. WHERE does the data land?

- **B1. Queue server as relay** — server stores data, collector pulls from server
- **B2. Object storage (R2/S3)** — workers push to bucket, collector pulls from bucket
- **B3. Queue server's jobs.db** — ingest payloads already stored there
- **B4. Dedicated TCP receiver** — separate process on DO box, different port from queue

### C. WHAT gets transferred?

- **C1. Full DB file** — simple, atomic, grows with data
- **C2. Incremental row deltas** — small, needs watermark tracking on worker
- **C3. Compressed sqlite dump** — smaller than raw DB
- **C4. The ingest payload itself** — already in flight through the queue

### D. WHEN does export happen?

- **D1. After every ingest** — immediate, piggyback
- **D2. Periodic timer** — every N minutes
- **D3. Disk threshold** — at 70% full, push and prune
- **D4. On demand** — collector triggers (needs inbound access)

### E. HOW to handle pruning?

- **E1. Prune after confirmed push** — push delta → get ack → DELETE local
- **E2. Age-based prune** — DELETE WHERE timestamp < 30 days ago
- **E3. Collector sends "safe to prune" watermark** — two-phase
- **E4. Rotate DB files** — close current, rename, push old file, start fresh

## Two finalist approaches

### Approach 1: Worker drains through the queue (polite backpressure)

Worker submits `archive_batch` jobs to the existing queue only when queue is idle. Archive worker on DO box picks them up. Source worker prunes after ack.

- **Combo:** A2 + B1 + C2 + D2 + E1
- **Queue load:** <1%, only fires when `pending == 0`
- **Batch limit:** ~500 rows (1MB TCP payload limit)
- **New infra:** None

### Approach 2: TCP archive receiver on DO box, separate port

Worker pushes cold rows to a dedicated TCP receiver on port 8080. Same 4-byte framing as the queue. Queue on :9999 is completely untouched.

- **Combo:** A2 + B4 + C2 + D2 + E1
- **Queue load:** Zero
- **Batch limit:** ~5000+ rows (no queue payload limit)
- **New infra:** ~25-line TCP receiver on DO box
