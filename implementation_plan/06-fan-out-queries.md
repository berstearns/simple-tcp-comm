# Strategy 06: Fan-Out Queries Across Workers

## Goal

Answer aggregate questions across all users/workers ("how many total sessions?", "which users were active today?") by submitting the same query to every worker in parallel and merging results.

## Dependencies

- **01-user-worker-affinity.md** — targeted job submission
- **04-worker-health.md** — know which workers are online
- **05-per-user-databases.md** — workers need a local aggregation job since data is in many files

## The Problem

With per-user DB files (Strategy 05), there's no single `main.db` to query. Each worker has N user `.db` files. A query like `SELECT COUNT(*) FROM session_events` needs to:

1. Go to every online worker
2. Each worker opens every user `.db` and runs the query
3. Results come back to the caller for final merge

## Schema Changes

### Server-side (`jobs.db`)

```sql
CREATE TABLE IF NOT EXISTS fan_out_queries (
    id INTEGER PRIMARY KEY,
    query_sql TEXT,
    db_target TEXT,               -- "user_all" or a specific db name
    status TEXT DEFAULT 'pending', -- pending | collecting | done | partial | error
    job_ids TEXT,                  -- JSON array of sub-job IDs
    results TEXT,                  -- JSON merged result
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME
);
```

## File Changes

### `worker.py`

#### 1. New job: `query_all_users`

Runs a query against every user DB on this worker and returns combined results:

```python
@job("query_all_users")
def _query_all_users(p):
    sql = p["sql"]
    params = p.get("params", [])
    all_rows = []
    cols = None
    errors = []

    if not os.path.isdir(USER_DB_DIR):
        return {"error": "no user db directory"}

    for fname in os.listdir(USER_DB_DIR):
        if not fname.endswith(".db"):
            continue
        user_id = fname[:-3]  # strip .db
        db_path = os.path.join(USER_DB_DIR, fname)
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.execute(sql, params)
            if cols is None and cur.description:
                cols = [d[0] for d in cur.description]
                # Prepend user_id column
                cols = ["_user_id"] + cols
            rows = cur.fetchall()
            for row in rows:
                all_rows.append([user_id] + list(row))
            conn.close()
        except Exception as e:
            errors.append({"user_id": user_id, "error": str(e)})

    return {
        "cols": cols or [],
        "rows": all_rows,
        "user_count": len([f for f in os.listdir(USER_DB_DIR) if f.endswith(".db")]),
        "errors": errors if errors else None
    }
```

### `server.py`

#### 2. New op: `fan_out`

Submits one `query_all_users` job per online worker:

```python
if op == "fan_out":
    sql = msg["sql"]
    params = msg.get("params", [])
    online = db.execute("SELECT name FROM workers WHERE status='online'").fetchall()
    if not online:
        return {"ok": False, "err": "no online workers"}

    job_ids = []
    for (wname,) in online:
        cur = db.execute("INSERT INTO jobs(payload, target) VALUES(?, ?)",
            [json.dumps({"task": "query_all_users", "sql": sql, "params": params}),
             wname])
        job_ids.append(cur.lastrowid)

    db.execute("INSERT INTO fan_out_queries(query_sql, status, job_ids) VALUES(?, 'collecting', ?)",
               [sql, json.dumps(job_ids)])
    fan_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    log("INF", "fan_out", f"query #{fan_id} → {len(job_ids)} workers")
    return {"ok": True, "fan_out_id": fan_id, "job_ids": job_ids,
            "workers": len(online)}
```

#### 3. New op: `fan_out_status`

Checks sub-job completion and merges results:

```python
if op == "fan_out_status":
    row = db.execute("SELECT id, query_sql, status, job_ids, results FROM fan_out_queries WHERE id=?",
                     [msg["id"]]).fetchone()
    if not row:
        return {"ok": False, "err": "not found"}
    if row[2] == "done":
        return {"ok": True, "status": "done", "results": json.loads(row[4])}

    job_ids = json.loads(row[3])
    results = []
    completed = 0
    for jid in job_ids:
        j = db.execute("SELECT status, result, worker_name FROM jobs WHERE id=?", [jid]).fetchone()
        if j[0] == "done":
            completed += 1
            results.append({
                "worker": j[2],
                "result": json.loads(j[1]) if j[1] else None
            })

    all_done = completed == len(job_ids)
    if all_done:
        db.execute("""UPDATE fan_out_queries SET status='done', results=?,
            completed_at=CURRENT_TIMESTAMP WHERE id=?""",
            [json.dumps(results), msg["id"]])
        db.commit()

    return {"ok": True,
            "status": "done" if all_done else "collecting",
            "completed": completed, "total": len(job_ids),
            "results": results if all_done else None}
```

### `client.py`

#### 4. Add fan-out convenience functions

```python
def fan_out(sql, params=None):
    return rpc({"op": "fan_out", "sql": sql, "params": params or []})

def fan_out_status(fid):
    return rpc({"op": "fan_out_status", "id": fid})

def fan_out_wait(sql, params=None, timeout=60):
    """Submit fan-out query and block until all workers respond."""
    resp = fan_out(sql, params)
    if not resp.get("ok"):
        return resp
    fid = resp["fan_out_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = fan_out_status(fid)
        if s.get("status") == "done":
            return s["results"]
        time.sleep(2)
    raise TimeoutError(f"fan_out {fid} not done after {timeout}s")
```

#### 5. CLI dispatch

```python
elif cmd == "fan_out":
    sql = sys.argv[2]
    results = fan_out_wait(sql)
    for r in results:
        print(f"\n  === {r['worker']} ===")
        res = r.get("result", {})
        cols = res.get("cols", [])
        rows = res.get("rows", [])
        if cols:
            print(f"  {cols}")
        for row in rows[:20]:
            print(f"  {row}")
        if len(rows) > 20:
            print(f"  ... and {len(rows) - 20} more rows")
```

## Flow

```
1. Admin: python3 client.py fan_out "SELECT COUNT(*) as n FROM session_events"

2. client → server: {op: "fan_out", sql: "SELECT COUNT(*) ..."}

3. Server sees 3 online workers, creates 3 jobs:
   job #101: {task: "query_all_users", sql: "..."} target=worker-a
   job #102: {task: "query_all_users", sql: "..."} target=worker-b
   job #103: {task: "query_all_users", sql: "..."} target=worker-c
   Creates fan_out_queries row: id=7, job_ids=[101,102,103]

4. Each worker picks up its job:
   worker-a: opens u1.db, u2.db, u3.db → runs COUNT(*) on each
   Returns: {cols: ["_user_id", "n"], rows: [["u1", 500], ["u2", 300], ["u3", 200]]}

5. client polls fan_out_status(7) every 2s

6. All 3 jobs done → server merges:
   [{worker: "worker-a", result: {cols: [...], rows: [[u1,500],[u2,300],[u3,200]]}},
    {worker: "worker-b", result: {cols: [...], rows: [[u4,150],[u5,400]]}},
    {worker: "worker-c", result: {cols: [...], rows: [[u6,100]]}}]

7. Client receives merged results
   Total sessions = 500+300+200+150+400+100 = 1650
```

## Client-Side Aggregation

The server just concatenates results. The client (or the script calling `fan_out_wait`) does the final aggregation. Common patterns:

```python
results = client.fan_out_wait("SELECT COUNT(*) as n FROM session_events")

# SUM across workers
total = sum(
    sum(row[1] for row in r["result"]["rows"])  # [1] because [0] is _user_id
    for r in results
)

# Collect all rows
all_rows = []
for r in results:
    all_rows.extend(r["result"]["rows"])

# Per-user breakdown (already in the data via _user_id column)
for row in all_rows:
    print(f"  user {row[0]}: {row[1]} sessions")
```

## Edge Cases

### Worker offline during fan-out

Its sub-job stays pending. `fan_out_status` shows `collecting` with partial completion (`completed: 2, total: 3`). Client can either:
- Wait for timeout → accept partial results
- Add a `fan_out_status` option that returns partial results early

### Empty workers

A worker with no user DBs returns `{cols: [], rows: [], user_count: 0}`. No problem — just contributes nothing to the merge.

### Query errors on some user DBs

`query_all_users` collects errors per-user but continues. The `errors` field in the result shows which users failed. The caller decides if partial data is acceptable.

### Heavy queries

`query_all_users` opens every user DB sequentially. For 1000 users with a complex query, this could take minutes. Mitigations:
- Add a `LIMIT` in the SQL to cap per-user results
- Add a timeout per-user DB in the worker
- For heavy analytics, use the archive from Strategy 03 instead

## Verification

```bash
# 1. Ensure multiple user DBs exist on workers
python3 client.py submit '{"task": "init_user_db", "user_id": "fan-test-1"}'
python3 client.py submit '{"task": "init_user_db", "user_id": "fan-test-2"}'
# Wait for processing

# 2. Insert test data
python3 client.py submit '{"task":"query","db":"user:fan-test-1","sql":"INSERT INTO session_events(eventType,timestamp) VALUES('\''ENTER'\'',1000)"}'
python3 client.py submit '{"task":"query","db":"user:fan-test-2","sql":"INSERT INTO session_events(eventType,timestamp) VALUES('\''ENTER'\'',2000)"}'

# 3. Fan-out query
python3 client.py fan_out "SELECT COUNT(*) as n FROM session_events"
# Should show results from both users
```
