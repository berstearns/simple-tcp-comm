# Strategy 04: Worker Health Monitoring

## Goal

Detect when workers go offline, recover stuck jobs, and provide a system health summary. This is the ops safety net that prevents silent failures.

## Dependencies

None. This is a foundation strategy — implement first.

## Schema Changes

### Server-side (`jobs.db`)

```sql
ALTER TABLE workers ADD COLUMN status TEXT DEFAULT 'online';     -- online | stale | dead
ALTER TABLE workers ADD COLUMN missed_polls INTEGER DEFAULT 0;
```

## File Changes

### `server.py`

#### 1. `init_db()` — add columns

Same pattern as existing migrations (line 66-73):

```python
wcols = {r[1] for r in db.execute("PRAGMA table_info(workers)")}
if "status" not in wcols:
    db.execute("ALTER TABLE workers ADD COLUMN status TEXT DEFAULT 'online'")
if "missed_polls" not in wcols:
    db.execute("ALTER TABLE workers ADD COLUMN missed_polls INTEGER DEFAULT 0")
```

#### 2. New async task: `watchdog()`

Runs alongside the server as an asyncio background task. Checks every 30 seconds.

```python
STALE_TIMEOUT = int(os.environ.get("STALE_TIMEOUT", "60"))    # seconds
DEAD_TIMEOUT = int(os.environ.get("DEAD_TIMEOUT", "300"))     # seconds

async def watchdog():
    while True:
        await asyncio.sleep(30)
        db = sqlite3.connect(DB)
        try:
            # Mark stale workers (no poll in STALE_TIMEOUT seconds)
            db.execute("""UPDATE workers SET status='stale', missed_polls=missed_polls+1
                WHERE last_seen < datetime('now', ? || ' seconds')
                AND status='online'""", [f"-{STALE_TIMEOUT}"])

            # Mark dead workers (no poll in DEAD_TIMEOUT seconds)
            db.execute("""UPDATE workers SET status='dead'
                WHERE last_seen < datetime('now', ? || ' seconds')
                AND status != 'dead'""", [f"-{DEAD_TIMEOUT}"])

            # Reset stuck jobs from dead workers (untargeted only)
            # Targeted jobs should stay — their data is on that worker
            stuck = db.execute("""SELECT j.id, j.target FROM jobs j
                JOIN workers w ON j.worker_name = w.name
                WHERE j.status='running' AND w.status='dead'""").fetchall()

            for jid, target in stuck:
                if target is None:
                    # Untargeted: safe to reassign to any worker
                    db.execute("""UPDATE jobs SET status='pending',
                        worker_name=NULL, worker_ip=NULL WHERE id=?""", [jid])
                    log("WRN", "watch", f"reset untargeted stuck job #{jid}")
                else:
                    # Targeted: can't reassign, mark as stuck
                    log("WRN", "watch",
                        f"job #{jid} stuck on dead worker {target} (targeted, not reset)")

            db.commit()
        except Exception as e:
            log("ERR", "watch", f"watchdog error: {e}")
        finally:
            db.close()
```

#### 3. Start watchdog in `main()`

```python
async def main():
    port = int(os.environ.get("QUEUE_PORT", sys.argv[1] if len(sys.argv) > 1 else "9999"))
    init_db()
    log_startup(port, DB)
    srv = await asyncio.start_server(handle_client, "0.0.0.0", port)
    asyncio.create_task(watchdog())  # <-- add this
    async with srv:
        await srv.serve_forever()
```

#### 4. Modify poll handler — reset status on poll

When a worker polls, it's alive. Update status to `online` and reset `missed_polls`:

```python
# Replace the existing worker upsert (line 90):
db.execute("""INSERT OR REPLACE INTO workers(name, ip, version, last_seen, status, missed_polls)
    VALUES(?, ?, ?, CURRENT_TIMESTAMP, 'online', 0)""",
    [worker_name, worker_ip, worker_ver])
```

#### 5. Modify `workers` op — include health fields

```python
if op == "workers":
    rows = db.execute("""SELECT name, ip, version, last_seen, status, missed_polls
        FROM workers ORDER BY last_seen DESC""").fetchall()
    return {"ok": True, "workers": [
        {"name": r[0], "ip": r[1], "version": r[2], "last_seen": r[3],
         "status": r[4] or "online", "missed_polls": r[5] or 0} for r in rows]}
```

#### 6. New op: `health`

System-wide health summary in a single call:

```python
if op == "health":
    w_online = db.execute("SELECT COUNT(*) FROM workers WHERE status='online'").fetchone()[0]
    w_stale = db.execute("SELECT COUNT(*) FROM workers WHERE status='stale'").fetchone()[0]
    w_dead = db.execute("SELECT COUNT(*) FROM workers WHERE status='dead'").fetchone()[0]
    j_pending = db.execute("SELECT COUNT(*) FROM jobs WHERE status='pending'").fetchone()[0]
    j_running = db.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
    j_done = db.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0]
    j_stuck = db.execute("""SELECT COUNT(*) FROM jobs j
        JOIN workers w ON j.worker_name = w.name
        WHERE j.status='running' AND w.status='dead'""").fetchone()[0]
    return {"ok": True,
            "workers": {"online": w_online, "stale": w_stale, "dead": w_dead},
            "jobs": {"pending": j_pending, "running": j_running, "done": j_done, "stuck": j_stuck}}
```

### `client.py`

#### 7. Add health function

```python
def health(): return rpc({"op": "health"})
```

#### 8. Update workers display (line 58-63) for new fields

```python
elif cmd == "workers":
    resp = workers()
    if resp.get("ok"):
        for w in resp["workers"]:
            status_icon = {"online": "●", "stale": "○", "dead": "✕"}.get(w.get("status", "?"), "?")
            print(f"  {status_icon} {w['name']:20s}  {w.get('version','?'):8s}  "
                  f"{w['ip']:16s}  {w.get('status','?'):7s}  seen {w['last_seen']}")
```

#### 9. Add health CLI dispatch

```python
elif cmd == "health":
    h = health()
    if h.get("ok"):
        w = h["workers"]
        j = h["jobs"]
        print(f"  workers: {w['online']} online, {w['stale']} stale, {w['dead']} dead")
        print(f"  jobs:    {j['pending']} pending, {j['running']} running, {j['done']} done")
        if j['stuck'] > 0:
            print(f"  WARNING: {j['stuck']} stuck jobs on dead workers")
```

### `worker.py`

No changes. Workers already heartbeat implicitly through polling every `QUEUE_POLL` seconds.

## Behavior

```
Time    Event                               Worker Status    Action
─────   ──────────────────────              ──────────────   ──────
t+0     worker-a polls                      online           —
t+2     worker-a polls                      online           —
t+30    watchdog runs                       online           no issues
t+60    watchdog runs, worker-a last_seen   stale            missed_polls++
        is 60s ago (missed 30 polls)
t+90    watchdog runs                       stale            missed_polls++
t+300   watchdog runs, 300s since last      dead             reset untargeted
        poll from worker-a                                   stuck jobs
t+302   worker-a comes back, polls          online           missed_polls=0
```

## Edge Cases

### Worker temporarily offline (network blip)

Goes `stale` after 60s. If it comes back before 300s, goes back to `online`. Running jobs on it are fine — the worker is still processing, just can't reach the server to poll. When connection restores, acks come through normally.

### Targeted jobs on dead workers

A job with `target='dead-worker'` can't be reassigned to another worker because the data is on that worker's disk. The watchdog logs a warning but does NOT reset these. Resolution:
- Worker comes back → job resumes
- Worker is permanently dead → use Strategy 02 (migrator) to reassign users, then reset jobs

### Job running legitimately for a long time

A 10-minute `exec` job shouldn't be reset. The watchdog only resets jobs where the **worker** is dead, not where the job is old. A dead worker means no ack is ever coming.

### Clock issues

`last_seen` is set server-side (`CURRENT_TIMESTAMP` in SQLite), not by the worker. So clock skew between machines doesn't matter.

## Verification

```bash
# 1. Start server, start a worker, check health
python3 client.py health

# 2. Kill the worker, wait 60s, check
python3 client.py workers
# Should show: ○ worker-name  stale

# 3. Wait 300s (or set DEAD_TIMEOUT=30 for testing)
python3 client.py workers
# Should show: ✕ worker-name  dead

# 4. Submit an untargeted job while worker is dead
python3 client.py ping
# Job stays pending — no one to pick it up

# 5. Restart worker — it polls, goes online, picks up pending job
python3 client.py health
# stuck should be 0
```
