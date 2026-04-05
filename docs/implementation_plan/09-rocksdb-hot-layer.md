# Strategy 09: RocksDB Hot Write Layer (Per Worker)

## Status: Saved for later

## Goal

Replace direct SQLite writes on workers with a RocksDB buffer layer. Events land in RocksDB instantly (no write lock contention), then drain into local SQLite on a timer. This decouples ingestion speed from query/schema concerns.

## Dependencies

- None (can be implemented independently)
- Enhances **03-offline-collector** (collector reads from SQLite after consolidation, not from RocksDB)
- Enhances **05-per-user-databases** (RocksDB key prefix can be user_id, drain targets per-user DBs)

## Architecture

```
Event arrives (query job)
        │
        ▼
  RocksDB write ──── instant, no lock, no schema
  (per worker)
        │
        │ [consolidation timer: every 5 min]
        ▼
  Local SQLite ────── structured, queryable, existing schema
  (main.db / app7.db / logs.db)
        │
        │ [offline collector: 03-offline-collector.md]
        ▼
  Central archive ─── analytics, backup
```

## Key Design

### RocksDB Key Format

```
{table}:{user_id}:{timestamp}:{uuid}
```

- Prefix scan by table+user for targeted drains
- Timestamp ordering for watermark-based consolidation
- UUID ensures no collisions under concurrent writes

### RocksDB Value

Raw JSON of the event payload. No schema enforcement at this layer.

```json
{"eventType": "page_view", "timestamp": 1712345678000, "pageId": "ch3-p2", ...}
```

### Write Path (replaces direct SQLite INSERT in worker.py)

```python
import rocksdict, json, uuid, time

class HotStore:
    def __init__(self, path="/var/lib/myapp/rocks"):
        self.db = rocksdict.Rdict(path)

    def put(self, table, user_id, event):
        ts = event.get("timestamp", int(time.time() * 1000))
        key = f"{table}:{user_id}:{ts}:{uuid.uuid4().hex[:8]}"
        self.db[key] = json.dumps(event)

    def scan_prefix(self, prefix):
        """Yield (key, parsed_event) for all keys matching prefix."""
        for key, val in self.db.items():
            if key.startswith(prefix):
                yield key, json.loads(val)

    def delete_keys(self, keys):
        for k in keys:
            del self.db[k]
```

### Consolidation (new: consolidator thread or cron)

```python
import sqlite3, json, time, threading

CONSOLIDATION_INTERVAL = 300  # 5 minutes
# Map RocksDB table prefixes to SQLite DB paths and INSERT statements
TABLE_MAP = {
    "session_events": {
        "db": "/var/lib/myapp/app7.db",
        "sql": "INSERT OR IGNORE INTO session_events (eventType, timestamp, durationMs, chapterName, pageId, pageTitle, synced) VALUES (?,?,?,?,?,?,?)",
        "cols": ["eventType", "timestamp", "durationMs", "chapterName", "pageId", "pageTitle", "synced"],
    },
    # ... same pattern for annotation_records, chat_messages,
    #     page_interactions, app_launch_records, settings_changes
    "events": {
        "db": "/var/lib/myapp/logs.db",
        "sql": "INSERT OR IGNORE INTO events (...) VALUES (...)",
        "cols": [...],
    },
}

def consolidate(hot_store):
    """Drain RocksDB into local SQLite. Safe to re-run (uuid dedup)."""
    for table, conf in TABLE_MAP.items():
        conn = sqlite3.connect(conf["db"])
        drained_keys = []
        batch = []

        for key, event in hot_store.scan_prefix(f"{table}:"):
            row = tuple(event.get(c) for c in conf["cols"])
            batch.append(row)
            drained_keys.append(key)

        if batch:
            conn.execute("BEGIN")
            conn.executemany(conf["sql"], batch)
            conn.commit()
            hot_store.delete_keys(drained_keys)

        conn.close()

def consolidation_loop(hot_store):
    """Run as daemon thread inside worker."""
    while True:
        try:
            consolidate(hot_store)
        except Exception as e:
            print(f"consolidation error: {e}")
        time.sleep(CONSOLIDATION_INTERVAL)
```

### Integration Point in worker.py

Minimal change — swap the SQLite INSERT in the `query` handler with a RocksDB put:

```python
# Before (current):
#   conn.execute("INSERT INTO session_events ...", params)

# After:
#   hot_store.put("session_events", user_id, event_dict)
#   (consolidation thread handles SQLite insertion)
```

Start the consolidation thread alongside the worker:

```python
hot_store = HotStore()
threading.Thread(target=consolidation_loop, args=(hot_store,), daemon=True).start()
```

## File Changes

| File | Change |
|------|--------|
| `worker.py` | Import HotStore, init on startup, route writes through it, start consolidation thread |
| `infrastructure.sh` | Add `pip install rocksdict` to setup, create `/var/lib/myapp/rocks/` directory |
| `migrate.sh` | No change (SQLite schema unchanged, consolidation uses same tables) |

New files:
| File | Purpose |
|------|---------|
| `hot_store.py` | HotStore class + consolidation logic (~80 lines) |

## Crash Safety

- **Worker crashes mid-write**: RocksDB WAL ensures the put either completes or doesn't. No partial writes.
- **Worker crashes mid-consolidation**: Events stay in RocksDB, get drained on next run. UUID-based `INSERT OR IGNORE` prevents duplicates if a batch partially committed to SQLite.
- **RocksDB data dir lost**: Data in the hot buffer is lost. Only events not yet consolidated. Acceptable since SQLite is the durable tier.

## Disk Considerations

- RocksDB uses ~2x raw data size due to LSM levels + WAL
- With 5-minute drain cycles, hot buffer stays small (minutes of events)
- Set `max_write_buffer_number` and `write_buffer_size` to cap memory usage
- Ties into **02-backpressure-migration** — if disk pressure rises, increase consolidation frequency

## Verification

```bash
# 1. Install dependency
pip install rocksdict

# 2. Smoke test
python3 -c "
from rocksdict import Rdict
db = Rdict('/tmp/test-rocks')
db['hello'] = 'world'
assert db['hello'] == 'world'
del db['hello']
db.close()
print('ok')
"

# 3. Load test: write 10k events, consolidate, verify SQLite counts match
python3 -c "
from hot_store import HotStore, consolidate
import json
hs = HotStore('/tmp/test-hot')
for i in range(10000):
    hs.put('session_events', 'user1', {'eventType': 'test', 'timestamp': i})
consolidate(hs)
# check SQLite row count matches 10000
"
```

## When to Implement

This is a performance optimization. Implement when:
- Write contention on SQLite becomes measurable (workers blocking on locked DB)
- Event ingestion rate exceeds what SQLite WAL can absorb per worker
- You want to decouple the write-fast and query-structured concerns cleanly

Not urgent for current scale. Good foundation before scaling to many concurrent users per worker.
