"""DO server — TCP job queue backed by SQLite. Zero deps."""
import asyncio, sqlite3, json, struct, sys, os, time, env; env.load()

DB = os.environ.get("QUEUE_DB", "jobs.db")

# ── Colors ────────────────────────────────────────────────────
C = {
    "reset":   "\033[0m",
    "dim":     "\033[2m",
    "bold":    "\033[1m",
    "red":     "\033[91m",
    "green":   "\033[92m",
    "yellow":  "\033[93m",
    "blue":    "\033[94m",
    "magenta": "\033[95m",
    "cyan":    "\033[96m",
    "white":   "\033[97m",
    "bg_red":  "\033[41m",
    "bg_green":"\033[42m",
}

OP_COLORS = {
    "submit": "green", "poll": "blue", "ack": "magenta",
    "status": "cyan", "list": "dim", "delete": "red",
    "reset": "yellow",
}

def _ts():
    return time.strftime("%H:%M:%S")

def log(level, op, msg, addr=""):
    color = C.get(OP_COLORS.get(op, "white"), C["white"])
    lvl_color = {"INF": C["green"], "WRN": C["yellow"], "ERR": C["red"]}.get(level, C["white"])
    src = f" {C['dim']}← {addr}{C['reset']}" if addr else ""
    print(f"{C['dim']}{_ts()}{C['reset']} {lvl_color}{level}{C['reset']} {color}{C['bold']}{op:>7}{C['reset']} {msg}{src}", flush=True)

def log_startup(port, db):
    print(f"""
{C['cyan']}{C['bold']}╔══════════════════════════════════════════╗
║         TCP JOB QUEUE SERVER             ║
╚══════════════════════════════════════════╝{C['reset']}
  {C['green']}●{C['reset']} Port:  {C['bold']}{port}{C['reset']}
  {C['green']}●{C['reset']} DB:    {C['bold']}{db}{C['reset']}
  {C['green']}●{C['reset']} PID:   {C['bold']}{os.getpid()}{C['reset']}
  {C['dim']}  Waiting for connections...{C['reset']}
""", flush=True)

def log_connect(addr):
    print(f"{C['dim']}{_ts()}{C['reset']} {C['green']}CON{C['reset']} {C['bold']}connected{C['reset']}    {C['dim']}← {addr}{C['reset']}", flush=True)

def log_disconnect(addr):
    print(f"{C['dim']}{_ts()}{C['reset']} {C['yellow']}DIS{C['reset']} {C['dim']}disconnected ← {addr}{C['reset']}", flush=True)

# ── DB ────────────────────────────────────────────────────────
def init_db():
    db = sqlite3.connect(DB)
    db.execute("""CREATE TABLE IF NOT EXISTS jobs(
        id INTEGER PRIMARY KEY, status TEXT DEFAULT 'pending',
        payload TEXT, result TEXT, worker_name TEXT, worker_ip TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    db.execute("""CREATE TABLE IF NOT EXISTS workers(
        name TEXT PRIMARY KEY, ip TEXT, version TEXT,
        last_seen DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    db.commit()
    # migrate: add columns if missing (existing DBs)
    cols = {r[1] for r in db.execute("PRAGMA table_info(jobs)")}
    for col in ["worker_name", "worker_ip"]:
        if col not in cols:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
    wcols = {r[1] for r in db.execute("PRAGMA table_info(workers)")}
    if "version" not in wcols:
        db.execute("ALTER TABLE workers ADD COLUMN version TEXT")
    db.commit()
    return db

# ── Handlers ──────────────────────────────────────────────────
def handle(db, msg, addr=""):
    op = msg["op"]
    if op == "submit":
        cur = db.execute("INSERT INTO jobs(payload) VALUES(?)", [json.dumps(msg["payload"])])
        db.commit()
        task = msg["payload"].get("task", "?")
        log("INF", op, f"job {C['bold']}#{cur.lastrowid}{C['reset']} task={C['cyan']}{task}{C['reset']}", addr)
        return {"ok": True, "id": cur.lastrowid}
    if op == "poll":
        worker_name = msg.get("worker", "?")
        worker_ip = addr.split(":")[0] if addr else "?"
        worker_ver = msg.get("version", "?")
        # register/update worker
        db.execute("INSERT OR REPLACE INTO workers(name, ip, version, last_seen) VALUES(?, ?, ?, CURRENT_TIMESTAMP)",
                   [worker_name, worker_ip, worker_ver])
        row = db.execute("SELECT id, payload FROM jobs WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        if not row:
            log("INF", op, f"{C['dim']}empty queue{C['reset']} {C['dim']}[{worker_name}]{C['reset']}", addr)
            db.commit()
            return {"ok": True, "id": None}
        db.execute("UPDATE jobs SET status='running', worker_name=?, worker_ip=? WHERE id=?",
                   [worker_name, worker_ip, row[0]])
        db.commit()
        task = json.loads(row[1]).get("task", "?")
        log("INF", op, f"job {C['bold']}#{row[0]}{C['reset']} task={C['cyan']}{task}{C['reset']} → {C['yellow']}running{C['reset']} {C['dim']}[{worker_name}]{C['reset']}", addr)
        return {"ok": True, "id": row[0], "payload": json.loads(row[1])}
    if op == "ack":
        db.execute("UPDATE jobs SET status='done', result=? WHERE id=?",
                   [json.dumps(msg.get("result")), msg["id"]])
        db.commit()
        has_err = "error" in (msg.get("result") or {})
        status_str = f"{C['red']}error{C['reset']}" if has_err else f"{C['green']}done{C['reset']}"
        worker_name = msg.get("worker", "?")
        log("INF", op, f"job {C['bold']}#{msg['id']}{C['reset']} → {status_str} {C['dim']}[{worker_name}]{C['reset']}", addr)
        return {"ok": True}
    if op == "status":
        row = db.execute("SELECT id, status, payload, result, worker_name, worker_ip FROM jobs WHERE id=?", [msg["id"]]).fetchone()
        if not row:
            log("WRN", op, f"job #{msg['id']} {C['red']}not found{C['reset']}", addr)
            return {"ok": False, "err": "not found"}
        log("INF", op, f"job {C['bold']}#{row[0]}{C['reset']} is {C['yellow']}{row[1]}{C['reset']}", addr)
        return {"ok": True, "id": row[0], "status": row[1],
                "payload": json.loads(row[2]), "result": json.loads(row[3]) if row[3] else None,
                "worker": {"name": row[4], "ip": row[5]} if row[4] else None}
    if op == "list":
        rows = db.execute("SELECT id, status, created_at FROM jobs ORDER BY id DESC LIMIT ?",
                          [msg.get("n", 20)]).fetchall()
        counts = {s: sum(1 for r in rows if r[1] == s) for s in ["pending", "running", "done"]}
        log("INF", op, f"{C['dim']}{len(rows)} jobs{C['reset']} (P:{counts.get('pending',0)} R:{counts.get('running',0)} D:{counts.get('done',0)})", addr)
        return {"ok": True, "jobs": [{"id": r[0], "status": r[1], "ts": r[2]} for r in rows]}
    if op == "delete":
        db.execute("DELETE FROM jobs WHERE id=?", [msg["id"]])
        db.commit()
        log("WRN", op, f"job {C['bold']}#{msg['id']}{C['reset']} {C['red']}deleted{C['reset']}", addr)
        return {"ok": True}
    if op == "reset":
        db.execute("UPDATE jobs SET status='pending', result=NULL WHERE id=?", [msg["id"]])
        db.commit()
        log("WRN", op, f"job {C['bold']}#{msg['id']}{C['reset']} → {C['yellow']}pending{C['reset']}", addr)
        return {"ok": True}
    if op == "workers":
        rows = db.execute("SELECT name, ip, version, last_seen FROM workers ORDER BY last_seen DESC").fetchall()
        log("INF", op, f"{len(rows)} workers registered", addr)
        return {"ok": True, "workers": [{"name": r[0], "ip": r[1], "version": r[2], "last_seen": r[3]} for r in rows]}
    log("ERR", "???", f"unknown op: {C['red']}{op}{C['reset']}", addr)
    return {"ok": False, "err": "unknown op"}

# ── Network ───────────────────────────────────────────────────
async def handle_client(r, w):
    addr = w.get_extra_info("peername")
    addr_str = f"{addr[0]}:{addr[1]}" if addr else "?"
    log_connect(addr_str)
    db = sqlite3.connect(DB)
    try:
        while True:
            hdr = await r.readexactly(4)
            data = await r.readexactly(struct.unpack("!I", hdr)[0])
            resp = json.dumps(handle(db, json.loads(data), addr_str)).encode()
            w.write(struct.pack("!I", len(resp)) + resp)
            await w.drain()
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
    finally:
        log_disconnect(addr_str)
        w.close()
        db.close()

async def main():
    port = int(os.environ.get("QUEUE_PORT", sys.argv[1] if len(sys.argv) > 1 else "9999"))
    init_db()
    log_startup(port, DB)
    srv = await asyncio.start_server(handle_client, "0.0.0.0", port)
    async with srv:
        await srv.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
