"""DO server — TCP job queue backed by SQLite. Zero deps."""
import asyncio, sqlite3, json, struct, sys

DB = "jobs.db"

def init_db():
    db = sqlite3.connect(DB)
    db.execute("""CREATE TABLE IF NOT EXISTS jobs(
        id INTEGER PRIMARY KEY, status TEXT DEFAULT 'pending',
        payload TEXT, result TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    db.commit()
    return db

def handle(db, msg):
    op = msg["op"]
    if op == "submit":
        cur = db.execute("INSERT INTO jobs(payload) VALUES(?)", [json.dumps(msg["payload"])])
        db.commit()
        return {"ok": True, "id": cur.lastrowid}
    if op == "poll":
        row = db.execute("SELECT id, payload FROM jobs WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return {"ok": True, "id": None}
        db.execute("UPDATE jobs SET status='running' WHERE id=?", [row[0]])
        db.commit()
        return {"ok": True, "id": row[0], "payload": json.loads(row[1])}
    if op == "ack":
        db.execute("UPDATE jobs SET status='done', result=? WHERE id=?",
                   [json.dumps(msg.get("result")), msg["id"]])
        db.commit()
        return {"ok": True}
    if op == "status":
        row = db.execute("SELECT id, status, payload, result FROM jobs WHERE id=?", [msg["id"]]).fetchone()
        if not row:
            return {"ok": False, "err": "not found"}
        return {"ok": True, "id": row[0], "status": row[1],
                "payload": json.loads(row[2]), "result": json.loads(row[3]) if row[3] else None}
    if op == "list":
        rows = db.execute("SELECT id, status, created_at FROM jobs ORDER BY id DESC LIMIT ?",
                          [msg.get("n", 20)]).fetchall()
        return {"ok": True, "jobs": [{"id": r[0], "status": r[1], "ts": r[2]} for r in rows]}
    if op == "delete":
        db.execute("DELETE FROM jobs WHERE id=?", [msg["id"]])
        db.commit()
        return {"ok": True}
    if op == "reset":
        db.execute("UPDATE jobs SET status='pending', result=NULL WHERE id=?", [msg["id"]])
        db.commit()
        return {"ok": True}
    return {"ok": False, "err": "unknown op"}

async def handle_client(r, w):
    db = sqlite3.connect(DB)
    try:
        while True:
            hdr = await r.readexactly(4)
            data = await r.readexactly(struct.unpack("!I", hdr)[0])
            resp = json.dumps(handle(db, json.loads(data))).encode()
            w.write(struct.pack("!I", len(resp)) + resp)
            await w.drain()
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
    finally:
        w.close()
        db.close()

async def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    init_db()
    srv = await asyncio.start_server(handle_client, "0.0.0.0", port)
    print(f"queue @ :{port}")
    async with srv:
        await srv.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
