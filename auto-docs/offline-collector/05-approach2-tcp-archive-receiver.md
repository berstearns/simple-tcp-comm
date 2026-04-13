# Approach 2: TCP Archive Receiver on DO Box (Separate Port)

> From conversation: detailed implementation design for dedicated TCP receiver.

## Architecture

```
Worker (NAT'd)                         DO box
                                    ┌──────────────────────┐
  drain loop ──── TCP :8080 ────►   │ archive_receiver.py  │
  (4-byte len + JSON,               │ same framing as queue│
   cold rows, every 5 min)          │ → archive.db         │
                                    ├──────────────────────┤
  ingest polling ── TCP :9999 ───►  │ server.py (queue)    │
                                    └──────────────────────┘
```

Queue handles ingest on :9999. Receiver handles archive on :8080. Completely separate traffic paths.

## The receiver (~25 lines)

```python
#!/usr/bin/env python3
"""archive_receiver.py — TCP, same 4-byte framing as the queue."""
import socket, struct, json, sqlite3, os, threading

ARCHIVE_DB = os.environ.get("ARCHIVE_DB", "/root/archive.db")
PORT = int(os.environ.get("ARCHIVE_PORT", "8080"))

def handle(conn):
    raw = conn.recv(4)
    if len(raw) < 4: return conn.close()
    size = struct.unpack("!I", raw)[0]
    data = b""
    while len(data) < size: data += conn.recv(size - len(data))
    msg = json.loads(data)

    db = sqlite3.connect(ARCHIVE_DB)
    table, cols, rows, worker = msg["table"], msg["cols"], msg["rows"], msg["worker_name"]
    acols = ["_source_worker"] + cols
    sql = f"INSERT OR IGNORE INTO {table} ({','.join(acols)}) VALUES ({','.join(['?']*len(acols))})"
    before = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    db.executemany(sql, [(worker,) + tuple(r) for r in rows])
    db.commit()
    inserted = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] - before
    db.close()

    resp = json.dumps({"ok": True, "inserted": inserted}).encode()
    conn.sendall(struct.pack("!I", len(resp)) + resp)
    conn.close()

s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", PORT))
s.listen(16)
print(f"archive receiver on :{PORT}")
while True:
    c, _ = s.accept()
    threading.Thread(target=handle, args=(c,), daemon=True).start()
```

## Worker drain loop

```python
ARCHIVE_SERVER = ("137.184.225.153", 8080)

def _archive_send(msg):
    s = socket.socket()
    s.connect(ARCHIVE_SERVER)
    data = json.dumps(msg).encode()
    s.sendall(struct.pack("!I", len(data)) + data)
    resp = json.loads(_recv_exact(s, struct.unpack("!I", _recv_exact(s, 4))[0]))
    s.close()
    return resp

def drain_loop():
    while True:
        time.sleep(300)
        for table in TABLES:
            rows = local_db.execute(
                f"SELECT * FROM {table} WHERE timestamp < ? ORDER BY id LIMIT 5000",
                [now_ms - 3600_000]
            ).fetchall()
            if not rows: continue
            
            resp = _archive_send({
                "worker_name": WORKER_NAME,
                "table": table,
                "cols": col_names,
                "rows": rows
            })
            if resp.get("ok"):
                local_db.execute(f"DELETE FROM {table} WHERE id <= ?", [max_id])
                local_db.commit()
```

## Comparison to approach 1

| | Approach 1: Queue drain | Approach 2: TCP receiver |
|---|---|---|
| Queue load | Small (<1%) but nonzero | Zero |
| Batch size limit | ~500 rows (1MB TCP payload) | ~5000+ rows (no limit) |
| Drain speed | Slow (waits for queue idle) | Fast (independent path) |
| New infra | None | 25-line TCP server on DO box |
| Retry/tracking | Built in (queue stores job state) | DIY (retry on TCP error) |
