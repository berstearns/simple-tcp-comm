"""Home lab worker — polls DO server, runs jobs against local DBs."""
import socket, struct, json, time, sys, sqlite3, os, env; env.load()

SERVER = (os.environ.get("QUEUE_HOST", "127.0.0.1"), int(os.environ.get("QUEUE_PORT", "9999")))
POLL = int(os.environ.get("QUEUE_POLL", "2"))
WORKER_NAME = os.environ.get("WORKER_NAME", socket.gethostname())

# Parse DBS from env: "main=/path/main.db,logs=/path/logs.db"
# or fall back to hardcoded defaults
def _parse_dbs():
    raw = os.environ.get("QUEUE_DBS", "")
    if raw:
        return dict(pair.split("=", 1) for pair in raw.split(","))
    return {"main": "/var/lib/myapp/main.db", "logs": "/var/lib/myapp/logs.db"}

DBS = _parse_dbs()

def _recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf

def rpc(msg):
    s = socket.socket()
    s.connect(SERVER)
    data = json.dumps(msg).encode()
    s.sendall(struct.pack("!I", len(data)) + data)
    resp = json.loads(_recv_exact(s, struct.unpack("!I", _recv_exact(s, 4))[0]))
    s.close()
    return resp

HANDLERS = {}
def job(name):
    def dec(f): HANDLERS[name] = f; return f
    return dec

@job("query")
def _query(p):
    """Run SQL against a local sqlite DB. Expects: {db, sql, params?}"""
    conn = sqlite3.connect(DBS[p["db"]])
    cur = conn.execute(p["sql"], p.get("params", []))
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall() if cols else []
    conn.commit()
    conn.close()
    return {"cols": cols, "rows": rows}

@job("exec")
def _exec(p):
    """Run a shell command. Expects: {cmd}"""
    import subprocess
    r = subprocess.run(p["cmd"], shell=True, capture_output=True, text=True, timeout=300)
    return {"stdout": r.stdout[-10000:], "stderr": r.stderr[-5000:], "rc": r.returncode}

@job("ping")
def _ping(p):
    return {"pong": True}

def run_job(job_id, payload):
    task = payload.get("task", "ping")
    handler = HANDLERS.get(task)
    if not handler:
        return {"error": f"unknown task: {task}"}
    print(f"  job {job_id} [{task}]")
    try:
        return handler(payload)
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    print(f"worker '{WORKER_NAME}' polling {SERVER[0]}:{SERVER[1]} every {POLL}s")
    while True:
        try:
            resp = rpc({"op": "poll", "worker": WORKER_NAME})
            if resp.get("id"):
                result = run_job(resp["id"], resp["payload"])
                rpc({"op": "ack", "id": resp["id"], "result": result, "worker": WORKER_NAME})
            else:
                time.sleep(POLL)
        except (ConnectionRefusedError, ConnectionError) as e:
            print(f"  down: {e}, retry in 5s")
            time.sleep(5)
