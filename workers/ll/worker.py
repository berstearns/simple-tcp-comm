"""Language-learning comic reader worker — handles ll-specific jobs."""
import socket, struct, json, time, sys, sqlite3, os, signal, subprocess

# resolve env.py from project root
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import env; env.load()

SERVER = (os.environ.get("QUEUE_HOST", "127.0.0.1"), int(os.environ.get("QUEUE_PORT", "9999")))
POLL = int(os.environ.get("QUEUE_POLL", "2"))
WORKER_NAME = os.environ.get("WORKER_NAME", socket.gethostname()) + "-ll"

def _parse_dbs():
    raw = os.environ.get("QUEUE_DBS", "")
    if raw:
        return dict(pair.split("=", 1) for pair in raw.split(","))
    return {"ll": "/var/lib/myapp/ll.db"}

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
    s.settimeout(10)
    s.connect(SERVER)
    data = json.dumps(msg).encode()
    s.sendall(struct.pack("!I", len(data)) + data)
    resp = json.loads(_recv_exact(s, struct.unpack("!I", _recv_exact(s, 4))[0]))
    s.close()
    return resp

_shutdown = False
def _handle_sigterm(sig, frame):
    global _shutdown
    if _shutdown:
        print(f"\n  forced exit")
        sys.exit(1)
    _shutdown = True
    print(f"  received signal {sig}, finishing current job then exiting...")
signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)

def _git_version():
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5,
                           cwd=os.path.dirname(os.path.abspath(__file__)))
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"

VERSION = _git_version()

HANDLERS = {}
def job(name):
    def dec(f): HANDLERS[name] = f; return f
    return dec

def _ms():
    return int(time.time() * 1000)

def _conn(db="ll"):
    c = sqlite3.connect(DBS[db])
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c

# ── generic query (same as root worker) ────────────────────────

@job("query")
def _query(p):
    conn = _conn(p.get("db", "ll"))
    cur = conn.execute(p["sql"], p.get("params", []))
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall() if cols else []
    conn.commit()
    conn.close()
    return {"cols": cols, "rows": rows}

# ── learner lifecycle ───────────────────────────────────────────

@job("create_learner")
def _create_learner(p):
    now = _ms()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO learners(device_id, display_name, native_lang, target_lang, created_at, updated_at) "
        "VALUES(?, ?, ?, ?, ?, ?)",
        [p["device_id"], p.get("display_name"), p["native_lang"], p["target_lang"], now, now])
    lid = cur.lastrowid
    conn.commit()
    conn.close()
    return {"learner_id": lid}

# ── app session ─────────────────────────────────────────────────

@job("app_session_start")
def _app_session_start(p):
    now = _ms()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO app_sessions(learner_id, started_at) VALUES(?, ?)",
        [p["learner_id"], now])
    sid = cur.lastrowid
    conn.execute(
        "INSERT INTO events(learner_id, ts, entity_type, entity_id, event_name, event_category) "
        "VALUES(?, ?, 'app_session', ?, 'app.foreground', 'session')",
        [p["learner_id"], now, sid])
    conn.commit()
    conn.close()
    return {"app_session_id": sid}

@job("app_session_end")
def _app_session_end(p):
    now = _ms()
    reason = p.get("reason", "background")
    conn = _conn()
    conn.execute(
        "UPDATE app_sessions SET ended_at=?, end_reason=? WHERE id=?",
        [now, reason, p["app_session_id"]])
    conn.execute(
        "INSERT INTO events(learner_id, ts, entity_type, entity_id, event_name, event_category, payload) "
        "VALUES(?, ?, 'app_session', ?, 'app.background', 'session', ?)",
        [p["learner_id"], now, p["app_session_id"], json.dumps({"reason": reason})])
    conn.commit()
    conn.close()
    return {"ok": True}

# ── app interaction ─────────────────────────────────────────────

@job("app_interact")
def _app_interact(p):
    now = _ms()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO app_interactions(app_session_id, action, target, value, ts) "
        "VALUES(?, ?, ?, ?, ?)",
        [p["app_session_id"], p["action"], p.get("target"), p.get("value"), now])
    aid = cur.lastrowid
    conn.execute(
        "INSERT INTO events(learner_id, ts, entity_type, entity_id, event_name, event_category) "
        "VALUES(?, ?, 'app_interaction', ?, ?, 'ui')",
        [p["learner_id"], now, aid, f"app.{p['action']}"])
    conn.commit()
    conn.close()
    return {"app_interaction_id": aid}

# ── comic session ───────────────────────────────────────────────

@job("comic_session_start")
def _comic_session_start(p):
    now = _ms()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO comic_sessions(app_session_id, comic_id, started_at) VALUES(?, ?, ?)",
        [p["app_session_id"], p["comic_id"], now])
    sid = cur.lastrowid
    conn.execute(
        "INSERT INTO events(learner_id, ts, entity_type, entity_id, event_name, event_category, payload) "
        "VALUES(?, ?, 'comic_session', ?, 'comic.open', 'session', ?)",
        [p["learner_id"], now, sid, json.dumps({"comic_id": p["comic_id"]})])
    conn.commit()
    conn.close()
    return {"comic_session_id": sid}

@job("comic_session_end")
def _comic_session_end(p):
    now = _ms()
    reason = p.get("reason", "back")
    conn = _conn()
    conn.execute(
        "UPDATE comic_sessions SET ended_at=?, end_reason=? WHERE id=?",
        [now, reason, p["comic_session_id"]])
    conn.execute(
        "INSERT INTO events(learner_id, ts, entity_type, entity_id, event_name, event_category) "
        "VALUES(?, ?, 'comic_session', ?, 'comic.close', 'session')",
        [p["learner_id"], now, p["comic_session_id"]])
    conn.commit()
    conn.close()
    return {"ok": True}

# ── page session ────────────────────────────────────────────────

@job("page_session_start")
def _page_session_start(p):
    now = _ms()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO page_sessions(comic_session_id, page_id, started_at) VALUES(?, ?, ?)",
        [p["comic_session_id"], p["page_id"], now])
    sid = cur.lastrowid
    conn.execute(
        "INSERT INTO events(learner_id, ts, entity_type, entity_id, event_name, event_category, payload) "
        "VALUES(?, ?, 'page_session', ?, 'page.enter', 'reading', ?)",
        [p["learner_id"], now, sid, json.dumps({"page_id": p["page_id"]})])
    conn.commit()
    conn.close()
    return {"page_session_id": sid}

@job("page_session_end")
def _page_session_end(p):
    now = _ms()
    conn = _conn()
    conn.execute(
        "UPDATE page_sessions SET ended_at=?, scroll_depth=? WHERE id=?",
        [now, p.get("scroll_depth"), p["page_session_id"]])
    conn.execute(
        "INSERT INTO events(learner_id, ts, entity_type, entity_id, event_name, event_category) "
        "VALUES(?, ?, 'page_session', ?, 'page.leave', 'reading')",
        [p["learner_id"], now, p["page_session_id"]])
    conn.commit()
    conn.close()
    return {"ok": True}

# ── page interaction ────────────────────────────────────────────

@job("page_interact")
def _page_interact(p):
    now = _ms()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO page_interactions(page_session_id, action, from_page_id, to_page_id, ts) "
        "VALUES(?, ?, ?, ?, ?)",
        [p["page_session_id"], p["action"], p.get("from_page_id"), p.get("to_page_id"), now])
    pid = cur.lastrowid
    conn.execute(
        "INSERT INTO events(learner_id, ts, entity_type, entity_id, event_name, event_category) "
        "VALUES(?, ?, 'page_interaction', ?, ?, 'navigation')",
        [p["learner_id"], now, pid, f"page.{p['action']}"])
    conn.commit()
    conn.close()
    return {"page_interaction_id": pid}

# ── bubble session ──────────────────────────────────────────────

@job("bubble_session_start")
def _bubble_session_start(p):
    now = _ms()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO bubble_sessions(page_session_id, bubble_id, trigger, showed_translation, played_audio, started_at) "
        "VALUES(?, ?, ?, ?, ?, ?)",
        [p["page_session_id"], p["bubble_id"], p.get("trigger", "tap"),
         p.get("showed_translation", 0), p.get("played_audio", 0), now])
    sid = cur.lastrowid
    conn.execute(
        "INSERT INTO events(learner_id, ts, entity_type, entity_id, event_name, event_category, payload) "
        "VALUES(?, ?, 'bubble_session', ?, 'bubble.zoom_in', 'reading', ?)",
        [p["learner_id"], now, sid, json.dumps({"bubble_id": p["bubble_id"], "trigger": p.get("trigger", "tap")})])
    conn.commit()
    conn.close()
    return {"bubble_session_id": sid}

@job("bubble_session_end")
def _bubble_session_end(p):
    now = _ms()
    conn = _conn()
    conn.execute(
        "UPDATE bubble_sessions SET ended_at=?, showed_translation=?, played_audio=? WHERE id=?",
        [now, p.get("showed_translation", 0), p.get("played_audio", 0), p["bubble_session_id"]])
    conn.execute(
        "INSERT INTO events(learner_id, ts, entity_type, entity_id, event_name, event_category) "
        "VALUES(?, ?, 'bubble_session', ?, 'bubble.zoom_out', 'reading')",
        [p["learner_id"], now, p["bubble_session_id"]])
    conn.commit()
    conn.close()
    return {"ok": True}

# ── bubble annotation ───────────────────────────────────────────

@job("bubble_annotate")
def _bubble_annotate(p):
    now = _ms()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO bubble_annotations(bubble_session_id, annotation_id, ts) VALUES(?, ?, ?)",
        [p["bubble_session_id"], p["annotation_id"], now])
    aid = cur.lastrowid
    conn.execute(
        "INSERT INTO events(learner_id, ts, entity_type, entity_id, event_name, event_category, payload) "
        "VALUES(?, ?, 'bubble_annotation', ?, 'bubble.annotate', 'annotation', ?)",
        [p["learner_id"], now, aid, json.dumps({"annotation_id": p["annotation_id"]})])
    conn.commit()
    conn.close()
    return {"bubble_annotation_id": aid}

# ── word interaction ────────────────────────────────────────────

@job("word_interact")
def _word_interact(p):
    now = _ms()
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO word_interactions(bubble_session_id, word_id, interaction, showed_translation, played_audio, added_to_vocab, ts) "
        "VALUES(?, ?, ?, ?, ?, ?, ?)",
        [p["bubble_session_id"], p["word_id"], p.get("interaction", "tap"),
         p.get("showed_translation", 0), p.get("played_audio", 0),
         p.get("added_to_vocab", 0), now])
    wid = cur.lastrowid
    event_name = "word.tap"
    if p.get("showed_translation"): event_name = "word.translation_shown"
    if p.get("added_to_vocab"):     event_name = "word.added_to_vocab"
    conn.execute(
        "INSERT INTO events(learner_id, ts, entity_type, entity_id, event_name, event_category, payload) "
        "VALUES(?, ?, 'word_interaction', ?, ?, ?, ?)",
        [p["learner_id"], now, wid, event_name,
         "vocab" if p.get("added_to_vocab") else "reading",
         json.dumps({"word_id": p["word_id"], "interaction": p.get("interaction", "tap")})])
    conn.commit()
    conn.close()
    return {"word_interaction_id": wid}

# ── ping ────────────────────────────────────────────────────────

@job("ping")
def _ping(p):
    return {"pong": True}

# ── main loop ───────────────────────────────────────────────────

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
    print(f"ll-worker '{WORKER_NAME}' v{VERSION} polling {SERVER[0]}:{SERVER[1]} every {POLL}s")
    print(f"  dbs: {DBS}")
    while not _shutdown:
        try:
            resp = rpc({"op": "poll", "worker": WORKER_NAME, "version": VERSION})
            if resp.get("id"):
                result = run_job(resp["id"], resp["payload"])
                if not _shutdown:
                    rpc({"op": "ack", "id": resp["id"], "result": result, "worker": WORKER_NAME})
            else:
                print(f"waiting {POLL} seconds.")
                time.sleep(POLL)
        except OSError as e:
            print(f"  down: {e}, retry in 5s")
            time.sleep(5)
    print(f"ll-worker '{WORKER_NAME}' shutting down gracefully")
