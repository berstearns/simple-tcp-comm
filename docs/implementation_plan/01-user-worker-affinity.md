# Strategy 01: User-Worker Affinity

## Goal

Route all jobs for a given learner to the specific worker that holds their data. New learners get assigned to the least-loaded worker (sticky first-touch).

## Dependencies

None. This is the foundation — strategies 02, 03, 05, 06 build on it.

## Schema Changes

### Server-side (`jobs.db`)

```sql
-- New table: tracks which worker owns each user's data
CREATE TABLE IF NOT EXISTS user_affinity (
    user_id     TEXT PRIMARY KEY,
    worker_name TEXT NOT NULL,
    status      TEXT DEFAULT 'active',   -- active | migrating | frozen
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_job_at DATETIME
);

-- New column on jobs: which worker this job is targeted at
ALTER TABLE jobs ADD COLUMN target TEXT;  -- NULL = any worker can grab it
```

### Worker-side

No changes.

## File Changes

### `server.py`

#### 1. `init_db()` — add user_affinity table and target column

After the existing `CREATE TABLE IF NOT EXISTS jobs(...)` and workers table:

```python
db.execute("""CREATE TABLE IF NOT EXISTS user_affinity(
    user_id TEXT PRIMARY KEY, worker_name TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_job_at DATETIME)""")
```

Add `target` column migration (same pattern as existing column migrations at line 66-73):

```python
if "target" not in cols:
    db.execute("ALTER TABLE jobs ADD COLUMN target TEXT")
```

#### 2. New function `resolve_target(db, msg)`

Called from the submit handler. Extracts `user_id` from `msg["payload"]` or `msg` top-level.

```python
def resolve_target(db, msg):
    user_id = msg.get("user_id") or msg.get("payload", {}).get("user_id")
    if not user_id:
        return msg.get("target")  # explicit target or None

    # Check existing affinity
    row = db.execute("SELECT worker_name, status FROM user_affinity WHERE user_id=?",
                     [user_id]).fetchone()
    if row:
        db.execute("UPDATE user_affinity SET last_job_at=CURRENT_TIMESTAMP WHERE user_id=?",
                   [user_id])
        return row[0]  # always route to assigned worker

    # First touch: assign to least-loaded worker
    best = db.execute("""
        SELECT w.name FROM workers w
        LEFT JOIN user_affinity ua ON ua.worker_name = w.name AND ua.status = 'active'
        GROUP BY w.name
        ORDER BY COUNT(ua.user_id) ASC
        LIMIT 1""").fetchone()

    if not best:
        return msg.get("target")  # no workers registered yet

    db.execute("INSERT INTO user_affinity(user_id, worker_name) VALUES(?, ?)",
               [user_id, best[0]])
    return best[0]
```

#### 3. Modify `handle()` submit branch (line 79)

```python
if op == "submit":
    target = resolve_target(db, msg)
    cur = db.execute("INSERT INTO jobs(payload, target) VALUES(?, ?)",
                     [json.dumps(msg["payload"]), target])
    db.commit()
    # ... existing logging ...
    return {"ok": True, "id": cur.lastrowid}
```

#### 4. Modify `handle()` poll branch (line 92)

Change the pending job SELECT to filter by target:

```python
# Before (line 92):
row = db.execute("SELECT id, payload FROM jobs WHERE status='pending' ORDER BY id LIMIT 1").fetchone()

# After:
row = db.execute("""SELECT id, payload FROM jobs
    WHERE status='pending' AND (target IS NULL OR target=?)
    ORDER BY id LIMIT 1""", [worker_name]).fetchone()
```

This means:
- `target=NULL` → any worker can grab it (backwards compatible)
- `target='homelab'` → only the worker named `homelab` gets it

#### 5. New op `affinity`

```python
if op == "affinity":
    rows = db.execute("""SELECT user_id, worker_name, status, assigned_at, last_job_at
        FROM user_affinity ORDER BY last_job_at DESC LIMIT ?""",
        [msg.get("n", 50)]).fetchall()
    return {"ok": True, "affinities": [
        {"user_id": r[0], "worker": r[1], "status": r[2],
         "assigned_at": r[3], "last_job_at": r[4]} for r in rows]}
```

### `client.py`

#### 6. Add affinity convenience function

```python
def affinity(n=50): return rpc({"op": "affinity", "n": n})
```

#### 7. Modify submit to accept target

```python
def submit(payload, target=None):
    msg = {"op": "submit", "payload": payload}
    if target:
        msg["target"] = target
    return rpc(msg)
```

#### 8. Add CLI dispatch for affinity

```python
elif cmd == "affinity":
    resp = affinity()
    if resp.get("ok"):
        for a in resp["affinities"]:
            print(f"  {a['user_id']:20s} → {a['worker']:20s}  [{a['status']}]  last: {a['last_job_at']}")
```

### `worker.py`

No changes needed.

## Flow

```
1. Kotlin app syncs → backend receives payload with userId="u42"
2. Backend submits job: client.submit({"task": "sync", "user_id": "u42", "data": {...}})
3. server.py handle() → submit op → resolve_target(db, msg)
4. resolve_target checks user_affinity table:
   a. Row exists for u42 → return worker_name (e.g. "homelab")
   b. No row → pick least-loaded worker, INSERT affinity, return worker_name
5. Job inserted with target="homelab"
6. Workers poll:
   - homelab polls → SELECT WHERE target IS NULL OR target='homelab' → gets the job
   - other-worker polls → SELECT WHERE target IS NULL OR target='other-worker' → skips it
7. homelab processes job, acks result
```

## Edge Cases

### Race on first assignment

Two sync payloads for a brand-new user arrive simultaneously on different server connections (each has its own SQLite connection).

**Fix**: Use `INSERT OR IGNORE INTO user_affinity` then `SELECT`. Whoever wins the INSERT wins. Both reads get the same result afterwards. SQLite serializes writes at the file level.

### No workers registered yet

`resolve_target` returns `None`, job gets `target=NULL`. First worker to poll picks it up. The affinity row should be created retroactively in the ack handler when we know which worker ran it.

### Assigned worker is offline

Jobs pile up with `target='dead-worker'`. Strategy 04 (worker health) handles this — watchdog detects dead workers and can reassign users or reset jobs.

### Untargeted jobs still work

Ping, exec, and generic queries with no `user_id` get `target=NULL` and continue working exactly as before — any worker grabs them.

## Verification

```bash
# 1. Submit a job with user_id
python3 client.py submit '{"task": "ping", "user_id": "test-user-1"}'

# 2. Check affinity was created
python3 client.py affinity

# 3. Submit another job for same user — should go to same worker
python3 client.py submit '{"task": "ping", "user_id": "test-user-1"}'

# 4. Submit untargeted job — should be grabbed by any worker
python3 client.py ping

# 5. Verify with job list
python3 client.py ls
```
