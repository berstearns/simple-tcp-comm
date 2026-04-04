# Strategy 07: Job Priority & Automatic Retry

## Goal

Not all jobs are equal. Sync uploads should process before analytics queries. Failed jobs should retry automatically with exponential backoff instead of requiring manual `reset`.

## Dependencies

None. Implement alongside Strategy 04 in Phase 1.

## Schema Changes

### Server-side (`jobs.db`)

```sql
ALTER TABLE jobs ADD COLUMN priority INTEGER DEFAULT 5;       -- 1=highest, 9=lowest
ALTER TABLE jobs ADD COLUMN attempts INTEGER DEFAULT 0;
ALTER TABLE jobs ADD COLUMN max_attempts INTEGER DEFAULT 3;
ALTER TABLE jobs ADD COLUMN next_retry_at DATETIME;
ALTER TABLE jobs ADD COLUMN last_error TEXT;
```

New job status: `failed` (terminal — max attempts exhausted).

## Priority Levels (convention)

| Priority | Job Types | Rationale |
|----------|-----------|-----------|
| 1 | Migration jobs (dump/import/prune) | User frozen while migrating, minimize downtime |
| 3 | Sync uploads from Kotlin app | User-facing, latency matters |
| 5 | Default (query, exec, ping) | Normal operations |
| 7 | Analytics / fan-out queries | Background, can wait |
| 9 | Maintenance / archival / collection | Lowest priority, run when idle |

## File Changes

### `server.py`

#### 1. `init_db()` — add columns

```python
cols = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
for col, typ, default in [
    ("priority", "INTEGER", "5"),
    ("attempts", "INTEGER", "0"),
    ("max_attempts", "INTEGER", "3"),
    ("next_retry_at", "DATETIME", None),
    ("last_error", "TEXT", None),
]:
    if col not in cols:
        dflt = f" DEFAULT {default}" if default else ""
        db.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}{dflt}")
```

#### 2. Modify submit handler (line 79)

Accept `priority` and `max_attempts` from the message:

```python
if op == "submit":
    priority = msg.get("priority", 5)
    max_attempts = msg.get("max_attempts", 3)
    target = resolve_target(db, msg)  # from Strategy 01, or None
    cur = db.execute(
        "INSERT INTO jobs(payload, target, priority, max_attempts) VALUES(?, ?, ?, ?)",
        [json.dumps(msg["payload"]), target, priority, max_attempts])
    db.commit()
    # ... logging ...
    return {"ok": True, "id": cur.lastrowid}
```

#### 3. Modify poll handler (line 92)

Order by priority (ascending = highest first), and skip jobs not yet ready for retry:

```python
# Before:
row = db.execute("SELECT id, payload FROM jobs WHERE status='pending' ORDER BY id LIMIT 1").fetchone()

# After:
row = db.execute("""SELECT id, payload FROM jobs
    WHERE status='pending'
      AND (target IS NULL OR target=?)
      AND (next_retry_at IS NULL OR next_retry_at <= CURRENT_TIMESTAMP)
    ORDER BY priority ASC, id ASC
    LIMIT 1""", [worker_name]).fetchone()
```

Increment `attempts` when assigning:

```python
db.execute("""UPDATE jobs SET status='running', worker_name=?, worker_ip=?,
    attempts=attempts+1 WHERE id=?""", [worker_name, worker_ip, row[0]])
```

#### 4. Modify ack handler (line 103)

Handle retry on failure:

```python
if op == "ack":
    result = msg.get("result")
    has_err = "error" in (result or {})

    if has_err:
        job = db.execute("SELECT attempts, max_attempts FROM jobs WHERE id=?",
                         [msg["id"]]).fetchone()
        if job and job[0] < job[1]:
            # Retry with exponential backoff: 5s, 10s, 20s, 40s... max 300s
            backoff = min(2 ** job[0] * 5, 300)
            db.execute("""UPDATE jobs SET status='pending', result=?, last_error=?,
                next_retry_at=datetime('now', '+' || ? || ' seconds')
                WHERE id=?""",
                [json.dumps(result), str(result.get("error", "")),
                 str(backoff), msg["id"]])
            worker_name = msg.get("worker", "?")
            log("WRN", op, f"job #{msg['id']} failed (attempt {job[0]}/{job[1]}), "
                f"retry in {backoff}s {C['dim']}[{worker_name}]{C['reset']}", addr)
        else:
            # Max attempts exhausted — mark as permanently failed
            db.execute("UPDATE jobs SET status='failed', result=?, last_error=? WHERE id=?",
                [json.dumps(result), str(result.get("error", "")), msg["id"]])
            worker_name = msg.get("worker", "?")
            log("ERR", op, f"job #{msg['id']} {C['red']}FAILED{C['reset']} "
                f"after {job[0]} attempts {C['dim']}[{worker_name}]{C['reset']}", addr)
    else:
        db.execute("UPDATE jobs SET status='done', result=? WHERE id=?",
                   [json.dumps(result), msg["id"]])
        # ... existing success logging ...

    db.commit()
    return {"ok": True}
```

#### 5. Modify list handler (line 121)

Include `failed` in status counts:

```python
if op == "list":
    rows = db.execute("SELECT id, status, created_at FROM jobs ORDER BY id DESC LIMIT ?",
                      [msg.get("n", 20)]).fetchall()
    counts = {s: sum(1 for r in rows if r[1] == s)
              for s in ["pending", "running", "done", "failed"]}
    log("INF", op, f"{len(rows)} jobs (P:{counts.get('pending',0)} R:{counts.get('running',0)} "
        f"D:{counts.get('done',0)} F:{counts.get('failed',0)})", addr)
    return {"ok": True, "jobs": [{"id": r[0], "status": r[1], "ts": r[2]} for r in rows]}
```

#### 6. Modify status handler (line 112)

Return retry info:

```python
if op == "status":
    row = db.execute("""SELECT id, status, payload, result, worker_name, worker_ip,
        priority, attempts, max_attempts, next_retry_at, last_error
        FROM jobs WHERE id=?""", [msg["id"]]).fetchone()
    if not row:
        return {"ok": False, "err": "not found"}
    return {"ok": True, "id": row[0], "status": row[1],
            "payload": json.loads(row[2]),
            "result": json.loads(row[3]) if row[3] else None,
            "worker": {"name": row[4], "ip": row[5]} if row[4] else None,
            "priority": row[6], "attempts": row[7], "max_attempts": row[8],
            "next_retry_at": row[9], "last_error": row[10]}
```

### `client.py`

#### 7. Modify submit to accept priority and max_attempts

```python
def submit(payload, target=None, priority=5, max_attempts=3):
    msg = {"op": "submit", "payload": payload, "priority": priority,
           "max_attempts": max_attempts}
    if target:
        msg["target"] = target
    return rpc(msg)
```

#### 8. Convenience wrappers with default priorities

```python
def query(db, sql, params=None, priority=5):
    return submit({"task": "query", "db": db, "sql": sql, "params": params or []},
                  priority=priority)

def sync_upload(user_id, data):
    """Submit sync data with high priority."""
    return submit({"task": "sync_import", "user_id": user_id, "data": data},
                  priority=3)
```

## Retry Backoff Schedule

| Attempt | Backoff | Total wait |
|---------|---------|------------|
| 1 | 5s | 5s |
| 2 | 10s | 15s |
| 3 | 20s | 35s |
| 4 | 40s | 75s |
| 5 | 80s | 155s |
| 6 | 160s | 315s |
| 7+ | 300s (cap) | ... |

Default `max_attempts=3` means a failing job retries twice (5s + 10s) before going to `failed`.

## Flow

```
Submit: job #50, priority=3, max_attempts=3
  │
  ▼
Poll: worker picks it up (attempt 1)
  │
  ├─ Success → status='done' ✓
  │
  └─ Error → attempt 1 < max 3
       │
       ▼
     status='pending', next_retry_at = now + 5s
       │
       ▼ (5s later)
     Poll: worker picks it up (attempt 2)
       │
       ├─ Success → status='done' ✓
       │
       └─ Error → attempt 2 < max 3
            │
            ▼
          status='pending', next_retry_at = now + 10s
            │
            ▼ (10s later)
          Poll: worker picks it up (attempt 3)
            │
            ├─ Success → status='done' ✓
            │
            └─ Error → attempt 3 = max 3
                 │
                 ▼
               status='failed' (terminal) ✕
               last_error preserved for debugging
```

## Edge Cases

### Retry storms

A job failing due to a persistent issue (corrupt DB, bad SQL) retries `max_attempts` times then stops at `failed`. The `last_error` field preserves the reason for debugging.

### Priority starvation

A flood of priority-3 sync jobs could starve priority-7 analytics. For a solo dev with low traffic this won't happen. If needed later: every Nth poll, ignore priority and take the oldest pending job.

### Manual retry of failed jobs

The existing `reset` op sets status back to `pending`. For failed jobs, also reset `attempts`:

```python
if op == "reset":
    db.execute("""UPDATE jobs SET status='pending', result=NULL, last_error=NULL,
        attempts=0, next_retry_at=NULL WHERE id=?""", [msg["id"]])
```

### Backwards compatibility

Jobs submitted without `priority` or `max_attempts` get defaults (5 and 3). The poll query still works — existing jobs have `priority=5`, `next_retry_at=NULL` (which passes the `IS NULL` check).

## Verification

```bash
# 1. Submit with different priorities
python3 -c "
import client
client.submit({'task': 'ping'}, priority=9)  # low
client.submit({'task': 'ping'}, priority=1)  # high
client.submit({'task': 'ping'}, priority=5)  # medium
"

# 2. Check that high priority is processed first
# (stop worker, submit jobs, start worker, watch order)

# 3. Test retry — submit a job that will fail
python3 -c "
import client
client.submit({'task': 'query', 'db': 'nonexistent', 'sql': 'SELECT 1'}, max_attempts=3)
"

# 4. Watch server logs — should show retry attempts with backoff
# 5. After 3 failures:
python3 client.py ls
# Should show status=failed

# 6. Manual reset of failed job
python3 client.py reset <JOB_ID>
python3 client.py status <JOB_ID>
# Should show status=pending, attempts=0
```
