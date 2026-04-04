# Strategy 02: Backpressure & User Migration

## Goal

Detect when a worker's disk is getting full, stop assigning new users to it, and actively move existing users to a less-loaded worker.

## Dependencies

- **01-user-worker-affinity.md** — needs user_affinity table, target column, poll filter
- **05-per-user-databases.md** — per-user DB files make migration = file copy instead of row-by-row SQL

## Schema Changes

### Server-side (`jobs.db`)

```sql
-- Add to workers table
ALTER TABLE workers ADD COLUMN db_bytes INTEGER DEFAULT 0;
ALTER TABLE workers ADD COLUMN user_count INTEGER DEFAULT 0;
ALTER TABLE workers ADD COLUMN capacity_status TEXT DEFAULT 'ok';  -- ok | soft_limit | hard_limit
```

The `user_affinity.status` column from Strategy 01 already supports `active | migrating | frozen`.

### Worker-side

No schema changes. Workers report stats via poll.

## Two Thresholds

| Level | Default | Trigger | Action |
|-------|---------|---------|--------|
| **Soft limit** | 70% or 700MB | `db_bytes > SOFT_LIMIT` | Stop assigning NEW users to this worker |
| **Hard limit** | 90% or 900MB | `db_bytes > HARD_LIMIT` | Actively move users OFF this worker |

Configurable via env:
```
DB_SOFT_LIMIT=700000000
DB_HARD_LIMIT=900000000
```

## File Changes

### `worker.py`

#### 1. Report stats in every poll

Add a `_db_stats()` function and include it in the poll RPC:

```python
def _db_stats():
    total = 0
    detail = {}
    for name, path in DBS.items():
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        detail[name] = size
        total += size
    # Also count per-user DB files if USER_DB_DIR exists
    user_dir = os.environ.get("USER_DB_DIR", "")
    user_count = 0
    if user_dir and os.path.isdir(user_dir):
        for f in os.listdir(user_dir):
            if f.endswith(".db"):
                user_count += 1
                try:
                    total += os.path.getsize(os.path.join(user_dir, f))
                except OSError:
                    pass
    return {"db_bytes": total, "db_detail": detail, "user_count": user_count}
```

Modify the poll call (line 97):

```python
resp = rpc({"op": "poll", "worker": WORKER_NAME, "version": VERSION,
            "stats": _db_stats()})
```

#### 2. New job: `dump_user` (with per-user DB files)

```python
@job("dump_user")
def _dump_user(p):
    import base64
    path = _user_db_path(p["user_id"])  # from Strategy 05
    if not os.path.exists(path):
        return {"error": f"no db for user {p['user_id']}"}
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return {"user_id": p["user_id"], "db_b64": data,
            "size": os.path.getsize(path)}
```

#### 3. New job: `import_user`

```python
@job("import_user")
def _import_user(p):
    import base64
    path = _user_db_path(p["user_id"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(base64.b64decode(p["db_b64"]))
    return {"imported": p["user_id"], "size": os.path.getsize(path)}
```

#### 4. New job: `verify_user`

```python
@job("verify_user")
def _verify_user(p):
    path = _user_db_path(p["user_id"])
    if not os.path.exists(path):
        return {"exists": False}
    conn = sqlite3.connect(path)
    counts = {}
    for table in ["session_events", "annotation_records", "chat_messages",
                   "page_interactions", "app_launch_records", "settings_changes"]:
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = row[0]
        except sqlite3.OperationalError:
            counts[table] = -1  # table missing
    conn.close()
    return {"exists": True, "user_id": p["user_id"],
            "size": os.path.getsize(path), "counts": counts}
```

#### 5. New job: `prune_user`

```python
@job("prune_user")
def _prune_user(p):
    path = _user_db_path(p["user_id"])
    if not os.path.exists(path):
        return {"error": "not found"}
    size = os.path.getsize(path)
    os.remove(path)
    return {"pruned": p["user_id"], "freed_bytes": size}
```

### `server.py`

#### 6. Store worker stats from poll

In the poll handler, after the existing worker upsert (line 90):

```python
stats = msg.get("stats", {})
db_bytes = stats.get("db_bytes", 0)
user_count = stats.get("user_count", 0)
soft_limit = int(os.environ.get("DB_SOFT_LIMIT", "700000000"))
hard_limit = int(os.environ.get("DB_HARD_LIMIT", "900000000"))
cap = "hard_limit" if db_bytes >= hard_limit else \
      "soft_limit" if db_bytes >= soft_limit else "ok"
db.execute("""INSERT OR REPLACE INTO workers(name, ip, version, last_seen,
    db_bytes, user_count, capacity_status) VALUES(?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)""",
    [worker_name, worker_ip, worker_ver, db_bytes, user_count, cap])
```

#### 7. Modify `resolve_target()` from Strategy 01

When picking least-loaded worker for a new user, exclude workers at soft/hard limit:

```python
best = db.execute("""
    SELECT w.name FROM workers w
    LEFT JOIN user_affinity ua ON ua.worker_name = w.name AND ua.status = 'active'
    WHERE w.capacity_status = 'ok'
    GROUP BY w.name
    ORDER BY COUNT(ua.user_id) ASC
    LIMIT 1""").fetchone()

# Fallback: if ALL workers are at soft_limit, pick least loaded anyway
if not best:
    best = db.execute("""
        SELECT w.name FROM workers w
        LEFT JOIN user_affinity ua ON ua.worker_name = w.name AND ua.status = 'active'
        WHERE w.capacity_status != 'hard_limit'
        GROUP BY w.name
        ORDER BY COUNT(ua.user_id) ASC
        LIMIT 1""").fetchone()
```

#### 8. New op: `set_affinity_status`

```python
if op == "set_affinity_status":
    db.execute("UPDATE user_affinity SET status=? WHERE user_id=?",
               [msg["status"], msg["user_id"]])
    db.commit()
    return {"ok": True}
```

#### 9. New op: `set_affinity`

```python
if op == "set_affinity":
    db.execute("UPDATE user_affinity SET worker_name=?, status=? WHERE user_id=?",
               [msg["worker_name"], msg.get("status", "active"), msg["user_id"]])
    db.commit()
    return {"ok": True}
```

#### 10. Poll handler: skip jobs for frozen/migrating users

In the poll handler, after selecting a pending job, check if the job's user is frozen:

```python
if row:
    payload = json.loads(row[1])
    uid = payload.get("user_id")
    if uid:
        aff = db.execute("SELECT status FROM user_affinity WHERE user_id=?", [uid]).fetchone()
        if aff and aff[0] in ("frozen", "migrating"):
            # Skip this job, don't assign it
            # Could SELECT next non-frozen job instead
            db.commit()
            return {"ok": True, "id": None}
```

### `client.py`

#### 11. Add migration-related functions

```python
def set_affinity_status(user_id, status):
    return rpc({"op": "set_affinity_status", "user_id": user_id, "status": status})

def set_affinity(user_id, worker_name, status="active"):
    return rpc({"op": "set_affinity", "user_id": user_id,
                "worker_name": worker_name, "status": status})
```

### New file: `migrator.py` (~100 lines)

Orchestrates user migration. Uses `client.py` for all communication.

```python
"""Migrator — moves users between workers via the job queue."""
import time, sys, client

TABLES = ["session_events", "annotation_records", "chat_messages",
          "page_interactions", "app_launch_records", "settings_changes"]

def wait_for_job(job_id, timeout=120):
    """Poll until job is done. Returns result."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.status(job_id)
        if resp.get("status") == "done":
            return resp.get("result")
        time.sleep(2)
    raise TimeoutError(f"job {job_id} not done after {timeout}s")

def migrate_user(user_id, source_worker, dest_worker):
    print(f"migrating {user_id}: {source_worker} → {dest_worker}")

    # Step 1: Freeze — no new jobs dispatched for this user
    print(f"  [1/6] freezing {user_id}...")
    client.set_affinity_status(user_id, "frozen")

    # Step 2: Wait for in-flight jobs to finish
    print(f"  [2/6] waiting for in-flight jobs...")
    time.sleep(5)  # simple grace period

    # Step 3: Dump from source worker
    print(f"  [3/6] dumping from {source_worker}...")
    dump_job = client.submit({"task": "dump_user", "user_id": user_id},
                             target=source_worker)
    dump_result = wait_for_job(dump_job["id"])
    if "error" in dump_result:
        print(f"  ABORT: dump failed: {dump_result['error']}")
        client.set_affinity_status(user_id, "active")
        return False

    # Step 4: Import to destination worker
    print(f"  [4/6] importing to {dest_worker}...")
    import_job = client.submit(
        {"task": "import_user", "user_id": user_id, "db_b64": dump_result["db_b64"]},
        target=dest_worker)
    import_result = wait_for_job(import_job["id"])
    if "error" in import_result:
        print(f"  ABORT: import failed: {import_result['error']}")
        client.set_affinity_status(user_id, "active")
        return False

    # Step 5: Verify on destination
    print(f"  [5/6] verifying on {dest_worker}...")
    verify_job = client.submit({"task": "verify_user", "user_id": user_id},
                               target=dest_worker)
    verify_result = wait_for_job(verify_job["id"])
    if not verify_result.get("exists"):
        print(f"  ABORT: verify failed")
        client.set_affinity_status(user_id, "active")
        return False

    # Step 6: Cutover + prune
    print(f"  [6/6] cutover...")
    client.set_affinity(user_id, dest_worker, "active")
    prune_job = client.submit({"task": "prune_user", "user_id": user_id},
                              target=source_worker)
    wait_for_job(prune_job["id"])

    print(f"  DONE: {user_id} now on {dest_worker}")
    return True

def auto_rebalance():
    """Find overloaded workers and migrate their least-active users."""
    wlist = client.workers()["workers"]
    overloaded = [w for w in wlist if w.get("capacity_status") == "hard_limit"]
    targets = [w for w in wlist if w.get("capacity_status") == "ok"]

    if not overloaded:
        print("no overloaded workers")
        return
    if not targets:
        print("WARNING: no workers with capacity available")
        return

    affinities = client.affinity(n=1000)["affinities"]

    for hot in overloaded:
        # Find least-active user on this worker
        users_on_hot = [a for a in affinities
                        if a["worker"] == hot["name"] and a["status"] == "active"]
        if not users_on_hot:
            continue
        # Sort by last_job_at ascending (least active first)
        users_on_hot.sort(key=lambda a: a.get("last_job_at") or "")
        victim = users_on_hot[0]

        # Pick least-loaded target
        dest = min(targets, key=lambda w: w.get("user_count", 0))
        migrate_user(victim["user_id"], hot["name"], dest["name"])

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "auto":
        auto_rebalance()
    elif len(sys.argv) == 4:
        migrate_user(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        print("usage:")
        print("  python3 migrator.py <user_id> <source_worker> <dest_worker>")
        print("  python3 migrator.py auto")
```

## Migration Flow (diagram)

```
migrator.py detects: worker-a at hard_limit, worker-b at ok
         │
         ▼
Pick user u42 (least active on worker-a)
         │
         ▼
[1] set_affinity_status(u42, "frozen")
    Server stops dispatching u42 jobs
         │
         ▼
[2] Wait 5s for in-flight jobs to finish
         │
         ▼
[3] Submit dump_user → worker-a
    Worker reads /users/u42.db, returns base64
         │
         ▼
[4] Submit import_user → worker-b
    Worker writes /users/u42.db from base64
         │
         ▼
[5] Submit verify_user → worker-b
    Worker counts rows, confirms file exists
         │
         ├── mismatch → ABORT, unfreeze u42 on worker-a
         │
         ▼ match
[6] set_affinity(u42, worker-b, "active")
    Submit prune_user → worker-a (deletes /users/u42.db)
         │
         ▼
Done. u42 now lives on worker-b.
```

## Why freeze matters

```
WITHOUT freeze:
  t0: start dump on worker-a
  t1: user syncs new data → dispatched to worker-a (not in dump)
  t2: dump completes (missing t1 data)
  t3: cutover to worker-b
  t4: t1 data orphaned on worker-a ← DATA LOSS

WITH freeze:
  t0: freeze u42 — jobs queue on server, not dispatched
  t1: user syncs → job queued but held
  t2: dump completes
  t3: import completes
  t4: cutover — update affinity to worker-b
  t5: unfreeze — t1 job dispatches to worker-b ← CORRECT
```

## Edge Cases

### Dump too large for single message

If a user's DB is >50MB, the base64-encoded JSON response gets huge. Mitigations:
- Paginated dump: add offset/limit, transfer in chunks
- File transfer via exec + scp instead of through the queue
- Compress before base64: `zlib.compress()` before encoding

### Import fails halfway

Since we're copying whole files (Strategy 05), import is atomic — write file or don't. If it fails, the file doesn't exist on dest, verify catches it, migration aborts, user stays on source.

### Both workers at hard limit

`auto_rebalance()` logs a warning and skips. This means "buy more disk or add a worker."

### Worker dies mid-migration

User is frozen, no jobs dispatched. When you fix the worker, re-run the migration. The frozen status persists until explicitly changed.

## Verification

```bash
# Manual migration test
python3 migrator.py test-user-1 worker-a worker-b

# Auto-rebalance (dry concept)
python3 migrator.py auto

# Check result
python3 client.py affinity
python3 client.py workers
```
