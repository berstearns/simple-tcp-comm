# TCP Archive Receiver — Admission Control Protocol Design

> From conversation: designing a protocol where the receiver decides whether to accept a batch based on header metadata, with adaptive batch sizing feedback.

## Core idea

Split the message into two phases: **header first, payload after**. The receiver reads 16 bytes, decides accept or reject, and tells the worker before the worker sends the heavy payload. No wasted bandwidth shipping 5MB of rows to a busy receiver.

## Sequence diagram

```
Worker                                    Receiver
  │                                          │
  │──── HEADER (16 bytes) ──────────────────►│
  │     batch_size, row_count, table_id      │
  │                                          │ (check load, decide)
  │◄──── VERDICT (12 bytes) ────────────────│
  │      ACCEPT / REJECT / SHRINK            │
  │      suggested_batch_size                │
  │                                          │
  │──── PAYLOAD (batch_size bytes) ─────────►│  (only if ACCEPT)
  │                                          │  (INSERT OR IGNORE)
  │◄──── RECEIPT (12 bytes) ────────────────│
  │      inserted, skipped                   │
  │                                          │
```

Two round-trips per batch. But the first round-trip is 28 bytes total — microseconds. The heavy payload only moves if the receiver said yes.

## Wire format

### Header (worker → receiver, 16 bytes fixed)

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
├───────────────────────────────────────────────────────────────────┤
│                      payload_size (4 bytes)                       │
├───────────────────────────────────────────────────────────────────┤
│                      row_count (4 bytes)                          │
├───────────────────────────────────────────────────────────────────┤
│   table_id (1)   │   flags (1)      │    worker_id_hash (2)      │
├───────────────────────────────────────────────────────────────────┤
│                      reserved (4 bytes, zero)                     │
└───────────────────────────────────────────────────────────────────┘
```

- `payload_size`: how many bytes the JSON/binary payload will be if accepted
- `row_count`: how many rows in this batch
- `table_id`: 0-15 mapping to the 16 tables (saves sending the name every time)
- `flags`: bit 0 = compressed (zlib), bits 1-7 reserved
- `worker_id_hash`: first 2 bytes of hash of worker name (for logging, not routing)

### Verdict (receiver → worker, 12 bytes fixed)

```
├───────────────────────────────────────────────────────────────────┤
│   status (1)     │   reason (1)     │    padding (2)              │
├───────────────────────────────────────────────────────────────────┤
│                      max_batch_rows (4 bytes)                     │
├───────────────────────────────────────────────────────────────────┤
│                      max_batch_bytes (4 bytes)                    │
└───────────────────────────────────────────────────────────────────┘
```

- `status`: `0x01` = ACCEPT (send payload), `0x02` = REJECT (go away, try later), `0x03` = SHRINK (re-pack smaller)
- `reason`: `0x00` = ok, `0x01` = busy (active inserts), `0x02` = disk full, `0x03` = rate limited
- `max_batch_rows`: receiver's current suggestion for batch size. Worker respects this on NEXT call.
- `max_batch_bytes`: receiver's current max payload size it'll accept

### Payload (worker → receiver, variable, only after ACCEPT)

The actual row data. Format determined by `flags` byte in header.

### Receipt (receiver → worker, 12 bytes fixed)

```
├───────────────────────────────────────────────────────────────────┤
│                      inserted (4 bytes)                           │
├───────────────────────────────────────────────────────────────────┤
│                      skipped (4 bytes)                            │
├───────────────────────────────────────────────────────────────────┤
│                      max_batch_rows (4 bytes)                     │
└───────────────────────────────────────────────────────────────────┘
```

Worker uses `max_batch_rows` from the receipt to calibrate the next drain batch.

## Receiver admission control logic

```python
active_inserts = 0       # how many INSERT OR IGNORE ops running right now
last_insert_ms = 0       # how long the last insert took
disk_free = shutil.disk_usage("/").free

def decide(header):
    payload_size, row_count, table_id, flags = unpack_header(header)
    
    if disk_free < 100_000_000:            # < 100MB free
        return REJECT, DISK_FULL, 0, 0
    
    if active_inserts > 0:                  # already inserting
        return REJECT, BUSY, 500, 500_000
    
    if payload_size > 10_000_000:           # > 10MB, ask to shrink
        return SHRINK, OK, 1000, 5_000_000
    
    if row_count > 10000:                   # too many rows, ask to shrink
        return SHRINK, OK, 5000, 5_000_000
    
    # adaptive: if last insert was slow, suggest smaller batches
    if last_insert_ms > 2000:
        suggested = max(100, row_count // 2)
    elif last_insert_ms < 200:
        suggested = min(10000, row_count * 2)
    else:
        suggested = row_count
    
    return ACCEPT, OK, suggested, 10_000_000
```

## Worker adaptive loop

```python
batch_rows = 500       # starting point
batch_bytes = 500_000

def drain_loop():
    while True:
        time.sleep(300)
        for table_id, table in enumerate(TABLES):
            rows, cols = fetch_cold_rows(table, limit=batch_rows)
            if not rows: continue
            
            payload = serialize(cols, rows)
            
            # Phase 1: send header
            send_header(payload_size=len(payload), row_count=len(rows), table_id=table_id)
            verdict = recv_verdict()
            
            if verdict.status == REJECT:
                break  # receiver busy, try all tables later
            
            if verdict.status == SHRINK:
                batch_rows = verdict.max_batch_rows
                continue  # re-fetch with smaller limit next cycle
            
            # Phase 2: ACCEPT — send payload
            send_payload(payload)
            receipt = recv_receipt()
            
            # Phase 3: prune confirmed rows
            prune(table, rows)
            
            # Phase 4: adapt for next batch
            batch_rows = receipt.max_batch_rows
```

## Serialization options (fastest to slowest)

| Format | Serialize speed | Wire size (1000 rows) | Deserialize speed | Stdlib? |
|---|---|---|---|---|
| **struct.pack (fixed schema)** | Fastest | ~40KB | Fastest | Yes |
| **msgpack** | ~3x faster than JSON | ~60KB | ~3x faster | No (pip) |
| **JSON + zlib** | JSON speed, small wire | ~20KB | JSON + decompress | Yes |
| **JSON** | Baseline | ~120KB | Baseline | Yes |

### struct.pack (fastest, rigid)

For trusted entities with known schema. Zero parsing, zero allocations.

```python
# Both sides agree on column layout per table_id
SCHEMAS = {
    0: "!I 32s I 16s Q i 32s 32s 32s 64s i",  # session_events
}

# Worker packs:
payload = b"".join(struct.pack(SCHEMAS[table_id], *r) for r in rows)

# Receiver unpacks:
row_size = struct.calcsize(SCHEMAS[table_id])
for i in range(0, len(payload), row_size):
    row = struct.unpack(SCHEMAS[table_id], payload[i:i+row_size])
```

### JSON + zlib (pragmatic, flexible)

```python
# Worker:
payload = zlib.compress(json.dumps({"cols": cols, "rows": rows}).encode())
# Set flags bit 0 = 1 (compressed) in the header

# Receiver:
data = json.loads(zlib.decompress(payload))
```

3-6x smaller on the wire. Decompression is nearly free vs network latency. Schema-flexible. Stdlib only.

### Recommendation

**JSON + zlib for now.** Bottleneck is the internet link, not CPU. Zlib shrinks 4-5x which directly means faster transfers. Struct packing wins on CPU but gains disappear into network latency. The `flags` byte in the header lets you swap serialization later without changing the protocol.
