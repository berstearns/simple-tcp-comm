# Approach 1: Worker Drains Through the Queue (Polite Backpressure)

> From conversation: detailed implementation design for queue-based collection.

## How it works

Each worker runs a background thread alongside its ingest loop. Every 5 minutes it checks if the queue has pending jobs. If the queue is empty (no ingest traffic), it packs up to 500 old rows into a single `archive_batch` job and submits it. An archive worker on the DO box picks them up and appends to `archive.db`. Source worker prunes after ack.

## Throttle mechanism

```python
def drain_loop():
    while True:
        time.sleep(300)  # 5 min between attempts
        
        # polite: don't push if queue has real work
        pending = count_pending_jobs()
        if pending > 0:
            continue
        
        for table in TABLES:
            rows = local_db.execute(
                f"SELECT * FROM {table} WHERE timestamp < ? ORDER BY id LIMIT 500",
                [now_ms - 3600_000]  # older than 1 hour = cold
            ).fetchall()
            
            if not rows:
                continue
            
            resp = client.submit({
                "task": "archive_batch",
                "worker_name": WORKER_NAME,
                "table": table,
                "cols": [col names],
                "rows": rows
            })
            
            result = wait_for_done(resp["id"], timeout=60)
            
            if result.get("archived"):
                ids = [r[id_col_index] for r in rows]
                local_db.execute(
                    f"DELETE FROM {table} WHERE id IN ({','.join('?'*len(ids))})", ids
                )
                local_db.commit()
```

## Archive worker (on DO box)

```python
@job("archive_batch")
def _archive_batch(p):
    table = p["table"]
    cols = p["cols"]
    rows = p["rows"]
    worker = p["worker_name"]
    
    archive = sqlite3.connect(ARCHIVE_DB)
    archive_cols = ["_source_worker"] + cols
    placeholders = ",".join(["?"] * len(archive_cols))
    sql = f"INSERT OR IGNORE INTO {table} ({','.join(archive_cols)}) VALUES ({placeholders})"
    
    before = archive.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    archive.executemany(sql, [(worker,) + tuple(r) for r in rows])
    after = archive.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    archive.commit()
    archive.close()
    
    return {"archived": True, "inserted": after - before, "skipped": len(rows) - (after - before)}
```

## Numbers at 1000 users

| Metric | Value |
|---|---|
| Workers | ~10 (100 users each) |
| Drain check | 1 per worker per 5 min = 2/min total |
| Archive jobs when queue idle | at most 10 jobs × 16 tables = 160 per cycle |
| Throttled reality | 10-20 archive jobs in a quiet gap |
| Batch size | 500 rows per job, ~50KB JSON |
| Queue overhead | <1% of capacity |

## Pros / Cons

| Pro | Con |
|---|---|
| Zero new infrastructure | Archive speed depends on queue gaps |
| Same protocol, same tools, same monitoring | Large backlog takes a while to drain |
| Worker disk bounded (prunes after ack) | 500-row batch limit (1MB TCP payload) |
| Collector logic lives on the worker | Need archive worker on DO box |
