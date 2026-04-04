# Strategy 03: Offline DB Collector & Merge

## Goal

Periodically pull data from all workers into a consolidated archive DB for analytics, backup, or compliance. Optionally prune old data from workers to free disk.

## Dependencies

- **01-user-worker-affinity.md** — needs targeted job submission to direct queries to specific workers

## Schema Changes

### Archive DB (new file, e.g. `/var/lib/myapp/archive.db`)

Mirror the 6 learning app tables, plus metadata columns:

```sql
-- Same schema as per-user DBs, but with source tracking
CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY,
    eventType TEXT, timestamp INTEGER, durationMs INTEGER,
    chapterName TEXT, pageId TEXT, pageTitle TEXT, synced INTEGER,
    -- archive metadata
    source_user TEXT,
    source_worker TEXT,
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Same pattern for all 6 tables:
-- annotation_records, chat_messages, page_interactions,
-- app_launch_records, settings_changes
-- Each gets: source_user TEXT, source_worker TEXT, collected_at DATETIME

-- Track collection watermarks
CREATE TABLE IF NOT EXISTS collection_log (
    id INTEGER PRIMARY KEY,
    worker_name TEXT,
    user_id TEXT,
    table_name TEXT,
    rows_collected INTEGER,
    max_timestamp INTEGER,
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Server-side / Worker-side

No schema changes. Uses existing `query` job type on workers.

## File Changes

### New file: `collector.py` (~120 lines)

Runs on any machine with archive DB access (typically the server or your local machine). Uses `client.py` for all worker communication.

```python
"""Collector — merges all worker data into a consolidated archive."""
import sqlite3, json, time, sys, os, client

TABLES = ["session_events", "annotation_records", "chat_messages",
          "page_interactions", "app_launch_records", "settings_changes"]

ARCHIVE_DB = os.environ.get("ARCHIVE_DB", "/var/lib/myapp/archive.db")
BATCH_SIZE = 5000
POLL_INTERVAL = 2

def init_archive():
    """Create archive tables if they don't exist."""
    db = sqlite3.connect(ARCHIVE_DB)
    for table in TABLES:
        db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
            archive_id INTEGER PRIMARY KEY,
            source_user TEXT, source_worker TEXT,
            collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            original_data TEXT)""")  # store entire row as JSON for flexibility
    db.execute("""CREATE TABLE IF NOT EXISTS collection_log (
        id INTEGER PRIMARY KEY,
        worker_name TEXT, user_id TEXT, table_name TEXT,
        rows_collected INTEGER, collected_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    db.commit()
    db.close()

def wait_for_job(job_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.status(job_id)
        if resp.get("status") == "done":
            return resp.get("result")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"job {job_id} timed out")

def collect_worker(worker_name, user_ids):
    """Collect all data from a specific worker for given users."""
    archive = sqlite3.connect(ARCHIVE_DB)
    total_rows = 0

    for user_id in user_ids:
        for table in TABLES:
            # Submit a query job targeted at this worker
            sql = f"SELECT * FROM {table}"
            job = client.submit(
                {"task": "query", "db": f"user:{user_id}", "sql": sql},
                target=worker_name)

            try:
                result = wait_for_job(job["id"])
            except TimeoutError:
                print(f"  SKIP {worker_name}/{user_id}/{table}: timeout")
                continue

            if "error" in result:
                print(f"  SKIP {worker_name}/{user_id}/{table}: {result['error']}")
                continue

            cols = result.get("cols", [])
            rows = result.get("rows", [])

            if not rows:
                continue

            # Insert into archive
            for row in rows:
                row_data = json.dumps(dict(zip(cols, row)))
                archive.execute(
                    f"INSERT INTO {table}(source_user, source_worker, original_data) VALUES(?,?,?)",
                    [user_id, worker_name, row_data])

            archive.execute(
                "INSERT INTO collection_log(worker_name, user_id, table_name, rows_collected) VALUES(?,?,?,?)",
                [worker_name, user_id, table, len(rows)])

            total_rows += len(rows)
            print(f"  {worker_name}/{user_id}/{table}: {len(rows)} rows")

    archive.commit()
    archive.close()
    return total_rows

def collect_all():
    """Collect from all workers."""
    print(f"archive: {ARCHIVE_DB}")
    init_archive()

    # Get all workers
    wlist = client.workers()["workers"]
    print(f"workers: {len(wlist)}")

    # Get all user affinities
    affinities = client.affinity(n=10000)["affinities"]

    # Group users by worker
    worker_users = {}
    for a in affinities:
        if a["status"] == "active":
            worker_users.setdefault(a["worker"], []).append(a["user_id"])

    total = 0
    for worker_name, user_ids in worker_users.items():
        print(f"\ncollecting from {worker_name} ({len(user_ids)} users)...")
        total += collect_worker(worker_name, user_ids)

    print(f"\ndone. {total} total rows archived.")

def prune_old(days=90):
    """Submit DELETE jobs to workers for data older than N days."""
    import datetime
    cutoff = int((datetime.datetime.now() -
                  datetime.timedelta(days=days)).timestamp() * 1000)

    affinities = client.affinity(n=10000)["affinities"]
    worker_users = {}
    for a in affinities:
        if a["status"] == "active":
            worker_users.setdefault(a["worker"], []).append(a["user_id"])

    for worker_name, user_ids in worker_users.items():
        for user_id in user_ids:
            for table in TABLES:
                job = client.submit(
                    {"task": "query", "db": f"user:{user_id}",
                     "sql": f"DELETE FROM {table} WHERE timestamp < ?",
                     "params": [cutoff]},
                    target=worker_name)
                print(f"  prune {worker_name}/{user_id}/{table}: job #{job['id']}")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "collect"
    if cmd == "collect":
        collect_all()
    elif cmd == "prune":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 90
        prune_old(days)
    else:
        print("usage:")
        print("  python3 collector.py collect")
        print("  python3 collector.py prune [days]")
```

## Flow

```
collector.py (cron: weekly/monthly)
     │
     ├─ client.workers() → [worker-a, worker-b]
     ├─ client.affinity() → {u1→worker-a, u2→worker-a, u3→worker-b}
     │
     ├─ For worker-a:
     │   ├─ submit query "SELECT * FROM session_events" db=user:u1, target=worker-a
     │   │   └─ wait → result rows → INSERT INTO archive
     │   ├─ submit query for u1/annotation_records ...
     │   ├─ submit query for u2/session_events ...
     │   └─ ...
     │
     ├─ For worker-b:
     │   ├─ submit query for u3/session_events, target=worker-b
     │   └─ ...
     │
     └─ Log collection metadata in collection_log
```

## Running the Collector

### One-shot (manual)

```bash
ARCHIVE_DB=/data/archive.db python3 collector.py collect
```

### Cron (automated)

```bash
# Add to crontab on server or any machine with access
# Weekly on Sunday at 3am:
0 3 * * 0 cd /path/to/simple-tcp-comm && ARCHIVE_DB=/data/archive.db python3 collector.py collect >> /var/log/collector.log 2>&1

# Monthly prune of data older than 90 days:
0 4 1 * * cd /path/to/simple-tcp-comm && python3 collector.py prune 90 >> /var/log/collector.log 2>&1
```

### As a supervisor job (alternative)

Add a second tmux session in `start_supervisor.sh` or create a `start_collector.sh` that runs collector on a timer loop.

## Edge Cases

### Worker offline during collection

Job stays pending indefinitely. `wait_for_job` times out after 120s, collector prints SKIP and moves on. Next run will re-collect from that worker (no watermark update on failure).

### Duplicate collection

If collector runs twice without pruning, it will insert duplicate rows into the archive. Mitigations:
- Add a `UNIQUE` constraint on `(source_user, source_worker, original_data)` with `INSERT OR IGNORE`
- Or use the `collection_log` to skip users/tables already collected this run
- Or accept duplicates and deduplicate at query time

### Large user DBs

The `SELECT *` returns all rows. For large tables, add pagination:
```sql
SELECT * FROM session_events ORDER BY id LIMIT 5000 OFFSET ?
```
Loop until fewer than 5000 rows returned.

### Archive DB grows huge

The archive itself is SQLite. For very large archives:
- Rotate monthly: `archive-2026-04.db`, `archive-2026-05.db`
- Or dump to CSV/Parquet for external analytics tools
- Or use DuckDB to query multiple SQLite files without merging

## Verification

```bash
# 1. Run collection
ARCHIVE_DB=/tmp/test-archive.db python3 collector.py collect

# 2. Check archive contents
sqlite3 /tmp/test-archive.db "SELECT source_user, source_worker, COUNT(*) FROM session_events GROUP BY 1,2"

# 3. Check collection log
sqlite3 /tmp/test-archive.db "SELECT * FROM collection_log ORDER BY collected_at DESC LIMIT 20"

# 4. Test prune (dry run — check jobs submitted)
python3 collector.py prune 90
python3 client.py ls
```
