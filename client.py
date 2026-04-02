"""PC client — submit jobs and check status. Zero deps."""
import socket, struct, json, sys

SERVER = ("YOUR_DO_IP", 9999)

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

def submit(payload):  return rpc({"op": "submit", "payload": payload})
def status(jid):      return rpc({"op": "status", "id": jid})
def ls(n=20):         return rpc({"op": "list", "n": n})
def delete(jid):      return rpc({"op": "delete", "id": jid})
def reset(jid):       return rpc({"op": "reset", "id": jid})

# -- convenience shortcuts for common jobs --
def query(db, sql, params=None):
    return submit({"task": "query", "db": db, "sql": sql, "params": params or []})

def execute(cmd):
    return submit({"task": "exec", "cmd": cmd})

def ping():
    return submit({"task": "ping"})

# python client.py query main "SELECT * FROM users LIMIT 5"
# python client.py exec "pg_dump maindb | gzip > /tmp/backup.gz"
# python client.py submit '{"task":"query","db":"logs","sql":"SELECT count(*) FROM events"}'
# python client.py status 1
# python client.py ls
# python client.py delete 3
# python client.py reset 2
# python client.py ping
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ls"
    if cmd == "submit":   print(submit(json.loads(sys.argv[2])))
    elif cmd == "query":  print(query(sys.argv[2], sys.argv[3]))
    elif cmd == "exec":   print(execute(sys.argv[2]))
    elif cmd == "ping":   print(ping())
    elif cmd == "status": print(status(int(sys.argv[2])))
    elif cmd == "delete": print(delete(int(sys.argv[2])))
    elif cmd == "reset":  print(reset(int(sys.argv[2])))
    elif cmd == "ls":     print(ls())
