"""app7 ingest worker — consumes the KMP UnifiedPayload schema v3.

=== TIMESTAMPED PINNED SNAPSHOT ===
This file is a clone of workers/app7/worker.py, pinned to the TCP sync
verification feature folder:
    /home/b/p/minimal-android-apps/app7-tcp-sync-direct-queue-client_20260409_031219/

It is used for the round-trip verification (emulator -> DO queue ->
local worker -> isolated sqlite DB) and must remain functionally
identical to the canonical worker except for:
  - WORKER_NAME suffix (so it's distinct in `client.py workers`)
  - default local DB path (isolated from other workers on this host)
  - schema path override to use this feature folder's pinned schema
Do NOT edit the handler logic here — keep it in sync with canonical.
====================================

Single job type: ``ingest_unified_payload``. The payload is a full
UnifiedPayload dict as emitted by the KMP producer (both the ``sync``
mode and the ``export`` mode produce the same shape).

The handler:
  1. Validates the envelope (schema_version, device_id, mode).
  2. Upserts the content catalog (chapters, pages, images) from the
     denormalized fields already carried inside the event rows.
  3. Writes one ingest_batches audit row per payload.
  4. Inserts into all 7 syncable tables using INSERT OR IGNORE keyed on
     (device_id, local_id), so re-sending the same export is a no-op.

Everything runs in a single sqlite transaction so a partial failure
leaves the DB untouched.
"""
import socket, struct, json, time, sys, sqlite3, os, signal, subprocess, re

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import env; env.load()

SERVER = (os.environ.get("QUEUE_HOST", "127.0.0.1"), int(os.environ.get("QUEUE_PORT", "9999")))
POLL = int(os.environ.get("QUEUE_POLL", "2"))
WORKER_NAME = os.environ.get("WORKER_NAME", socket.gethostname()) + "-app7-tcp-sync-verify"

# Clone-specific override: feature-folder pinned schema path
SCHEMA_PATH_OVERRIDE = {
    "app7": os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..",
        "dbs", "app7-tcp-sync-direct-queue-client_20260409_031219",
        "head_schema", "schema.sql")),
}

def _parse_dbs():
    raw = os.environ.get("QUEUE_DBS", "")
    if raw:
        return dict(pair.split("=", 1) for pair in raw.split(","))
    return {"app7": "/home/b/simple-tcp-comm-local-state/app7-tcp-sync-verify.db"}

DBS = _parse_dbs()
REPO_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

def _ensure_schema(db_name, schema_path=None):
    db_path = DBS.get(db_name)
    if not db_path:
        return
    if schema_path is None:
        # Clone-specific override: feature-folder pinned schema path
        if db_name in SCHEMA_PATH_OVERRIDE:
            schema_path = SCHEMA_PATH_OVERRIDE[db_name]
        else:
            schema_path = os.path.join(REPO_DIR, "dbs", db_name, "head_schema", "schema.sql")
    if not os.path.isfile(schema_path):
        print(f"  WARN: schema file not found: {schema_path}")
        return
    with open(schema_path) as f:
        sql = f.read()
    expected = set(re.findall(r'CREATE\s+TABLE\s+(\w+)', sql, re.IGNORECASE))
    if not expected:
        print(f"  WARN: no CREATE TABLE found in {schema_path}")
        return
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.isfile(db_path):
        conn = sqlite3.connect(db_path)
        actual = set(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
        conn.close()
        missing = expected - actual
        if not missing:
            return
        print(f"  {db_name}: missing tables {missing}, recreating db")
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(sql)
    conn.close()
    print(f"  {db_name}: schema applied from {schema_path}")

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

def _conn(db="app7"):
    c = sqlite3.connect(DBS[db])
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c

# ── generic query / ping ──────────────────────────────────────

@job("query")
def _query(p):
    conn = _conn(p.get("db", "app7"))
    cur = conn.execute(p["sql"], p.get("params", []))
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall() if cols else []
    conn.commit()
    conn.close()
    return {"cols": cols, "rows": rows}

@job("ping")
def _ping(p):
    return {"pong": True}

# ── content catalog upsert ────────────────────────────────────
# Derived from denormalized fields in UnifiedPayload. Called before
# any syncable rows are inserted so FK constraints hold.

def _upsert_catalog(conn, tables):
    chapters = set()
    pages = {}   # page_id -> (chapter_name, page_title)
    images = {}  # image_id -> page_id (may be None)

    for e in tables.get("session_events", []):
        if e.get("chapter_name"):
            chapters.add(e["chapter_name"])
        pid = e.get("page_id")
        if pid:
            prev = pages.get(pid, (None, None))
            pages[pid] = (e.get("chapter_name") or prev[0],
                          e.get("page_title") or prev[1])

    for e in tables.get("page_interactions", []):
        if e.get("chapter_name"):
            chapters.add(e["chapter_name"])
        pid = e.get("page_id")
        if pid:
            prev = pages.get(pid, (None, None))
            pages[pid] = (e.get("chapter_name") or prev[0], prev[1])

    for e in tables.get("app_launch_records", []):
        if e.get("current_chapter"):
            chapters.add(e["current_chapter"])
        pid = e.get("current_page_id")
        if pid:
            prev = pages.get(pid, (None, None))
            pages[pid] = (e.get("current_chapter") or prev[0], prev[1])

    # annotation/translation rows reference image_id; we don't know
    # the owning page from the payload, so insert images with NULL page_id.
    for a in tables.get("annotation_records", []):
        iid = a.get("image_id")
        if iid:
            images.setdefault(iid, None)
    for t in tables.get("region_translations", []):
        iid = t.get("image_id")
        if iid:
            images.setdefault(iid, None)

    if chapters:
        conn.executemany(
            "INSERT OR IGNORE INTO chapters(chapter_name) VALUES (?)",
            [(c,) for c in chapters])

    if pages:
        conn.executemany(
            "INSERT OR IGNORE INTO pages(page_id, chapter_name, page_title) VALUES (?, ?, ?)",
            [(pid, ch, pt) for pid, (ch, pt) in pages.items()])
        # Backfill chapter_name / page_title on pages that already existed but were bare.
        conn.executemany(
            """UPDATE pages
                  SET chapter_name = COALESCE(chapter_name, ?),
                      page_title   = COALESCE(page_title,   ?)
                WHERE page_id = ?""",
            [(ch, pt, pid) for pid, (ch, pt) in pages.items()])

    if images:
        conn.executemany(
            "INSERT OR IGNORE INTO images(image_id, page_id) VALUES (?, ?)",
            [(iid, pid) for iid, pid in images.items()])

# ── per-table inserters ───────────────────────────────────────
# All use INSERT OR IGNORE keyed on UNIQUE(device_id, local_id) so
# re-ingesting the same export is a no-op.

def _b(v):
    """Normalize a bool-ish JSON value to 0/1."""
    return 1 if v else 0

def _ingest_session_events(conn, device_id, user_id, rows):
    if not rows:
        return 0
    data = [(device_id, user_id, r["local_id"],
             r["event_type"], r["timestamp"], r.get("duration_ms"),
             r.get("chapter_name"), r.get("page_id"), r.get("page_title"),
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO session_events
             (device_id, user_id, local_id, event_type, timestamp, duration_ms,
              chapter_name, page_id, page_title, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        data)
    return cur.rowcount

def _ingest_annotations(conn, device_id, user_id, rows):
    if not rows:
        return 0
    data = [(device_id, user_id, r["local_id"],
             r["image_id"], r["box_index"],
             r["box_x"], r["box_y"], r["box_width"], r["box_height"],
             r["label"], r["timestamp"], r["tap_x"], r["tap_y"],
             r.get("region_type", "BUBBLE"),
             r.get("parent_bubble_index"), r.get("token_index"),
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO annotation_records
             (device_id, user_id, local_id, image_id, box_index,
              box_x, box_y, box_width, box_height,
              label, timestamp, tap_x, tap_y, region_type,
              parent_bubble_index, token_index, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        data)
    return cur.rowcount

def _ingest_chat(conn, device_id, user_id, rows):
    if not rows:
        return 0
    data = [(device_id, user_id, r["local_id"],
             r["sender"], r["text"], r["timestamp"],
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO chat_messages
             (device_id, user_id, local_id, sender, text, timestamp, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        data)
    return cur.rowcount

def _ingest_page_interactions(conn, device_id, user_id, rows):
    if not rows:
        return 0
    data = [(device_id, user_id, r["local_id"],
             r["interaction_type"], r["timestamp"],
             r.get("chapter_name"), r.get("page_id"),
             r.get("normalized_x"), r.get("normalized_y"), r.get("hit_result"),
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO page_interactions
             (device_id, user_id, local_id, interaction_type, timestamp,
              chapter_name, page_id, normalized_x, normalized_y, hit_result, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        data)
    return cur.rowcount

def _ingest_app_launches(conn, device_id, user_id, rows):
    if not rows:
        return 0
    data = [(device_id, user_id, r["local_id"],
             r["package_name"], r["timestamp"],
             r.get("current_chapter"), r.get("current_page_id"),
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO app_launch_records
             (device_id, user_id, local_id, package_name, timestamp,
              current_chapter, current_page_id, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        data)
    return cur.rowcount

def _ingest_settings(conn, device_id, user_id, rows):
    if not rows:
        return 0
    data = [(device_id, user_id, r["local_id"],
             r["setting_key"], r["old_value"], r["new_value"], r["timestamp"],
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO settings_changes
             (device_id, user_id, local_id, setting_key, old_value, new_value,
              timestamp, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        data)
    return cur.rowcount

def _ingest_translations(conn, device_id, user_id, rows):
    if not rows:
        return 0
    data = [(r["id"], device_id, user_id,
             r["image_id"], r["bubble_index"],
             r["original_text"], r["meaning_translation"], r["literal_translation"],
             r.get("source_language", "ja"), r.get("target_language", "en"))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO region_translations
             (id, device_id, user_id, image_id, bubble_index,
              original_text, meaning_translation, literal_translation,
              source_language, target_language)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        data)
    return cur.rowcount

# ── main handler ──────────────────────────────────────────────

@job("ingest_unified_payload")
def _ingest_unified_payload(p):
    schema_version = p.get("schema_version")
    if schema_version != 3:
        return {"accepted": False, "error": f"unsupported schema_version: {schema_version}"}
    mode = p.get("mode")
    if mode not in ("sync", "export"):
        return {"accepted": False, "error": f"invalid mode: {mode}"}
    device_id = p.get("device_id")
    if not device_id:
        return {"accepted": False, "error": "missing device_id"}

    user_id = p.get("user_id")
    app_version = p.get("app_version", "")
    export_ts = p.get("export_timestamp", 0)
    tables = p.get("tables") or {}
    sent_counts = {k: len(v) for k, v in tables.items() if isinstance(v, list)}

    conn = _conn()
    try:
        with conn:
            _upsert_catalog(conn, tables)

            cur = conn.execute(
                """INSERT INTO ingest_batches
                     (schema_version, mode, device_id, user_id, app_version,
                      export_timestamp, ingested_at, row_counts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [schema_version, mode, device_id, user_id, app_version,
                 export_ts, _ms(), json.dumps(sent_counts)])
            batch_id = cur.lastrowid

            inserted = {
                "session_events":      _ingest_session_events(conn, device_id, user_id, tables.get("session_events", [])),
                "annotation_records":  _ingest_annotations(conn, device_id, user_id, tables.get("annotation_records", [])),
                "chat_messages":       _ingest_chat(conn, device_id, user_id, tables.get("chat_messages", [])),
                "page_interactions":   _ingest_page_interactions(conn, device_id, user_id, tables.get("page_interactions", [])),
                "app_launch_records":  _ingest_app_launches(conn, device_id, user_id, tables.get("app_launch_records", [])),
                "settings_changes":    _ingest_settings(conn, device_id, user_id, tables.get("settings_changes", [])),
                "region_translations": _ingest_translations(conn, device_id, user_id, tables.get("region_translations", [])),
            }
    finally:
        conn.close()

    return {
        "accepted": True,
        "batch_id": batch_id,
        "counts": inserted,
        "sent": sent_counts,
    }

# ── main loop ─────────────────────────────────────────────────

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
    _ensure_schema("app7")
    print(f"app7-worker '{WORKER_NAME}' v{VERSION} polling {SERVER[0]}:{SERVER[1]} every {POLL}s")
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
    print(f"app7-worker '{WORKER_NAME}' shutting down gracefully")
