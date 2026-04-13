"""app7 ingest worker — consumes the KMP UnifiedPayload schema v4.

=== TIMESTAMPED PINNED SNAPSHOT (v4 / hierarchy-aware) ===
This file is a fork of workers/app7-tcp-sync-direct-queue-client_20260409_031219/,
pinned to the new explicit-db-hierarchy feature folder:
    /home/b/p/minimal-android-apps/app7-explicit-db-hierarchy_20260409_154552/

Key differences from the tcp-sync predecessor:
  - Accepts UnifiedPayload schema_version 3 OR 4 (v3 is treated as legacy
    with comic_id='_no_comic_' everywhere).
  - New catalog layout: comics table + composite (comic_id, chapter_name)
    and (comic_id, page_id) keys. _upsert_catalog iterates comic_id tuples.
  - Every event-table INSERT writes comic_id; v3 payloads backfill with
    '_no_comic_' so the round-trip from the tcp-sync folder still works.
  - WORKER_NAME suffix, local DB path, and schema path all updated to
    this feature folder's distinct values so both workers can coexist.
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
WORKER_NAME = os.environ.get("WORKER_NAME", socket.gethostname()) + "-app7-hierarchy-verify"

# Clone-specific override: feature-folder pinned schema path
SCHEMA_PATH_OVERRIDE = {
    "app7": os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..",
        "dbs", "app7-explicit-db-hierarchy_20260409_154552",
        "head_schema", "schema.sql")),
}

NO_COMIC_SENTINEL = "_no_comic_"

def _parse_dbs():
    raw = os.environ.get("QUEUE_DBS", "")
    if raw:
        return dict(pair.split("=", 1) for pair in raw.split(","))
    return {"app7": "/home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db"}

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
    """Build the catalog (comics, chapters, pages, images) from denormalized
    fields in the event rows. Composite-keyed on comic_id throughout so that
    two comics sharing a chapter name produce two distinct rows.
    """
    comics = set()                       # {comic_id}
    chapters = set()                     # {(comic_id, chapter_name)}
    pages = {}                           # (comic_id, page_id) -> (chapter_name, page_title)
    images = {}                          # image_id -> (comic_id, page_id)

    def _comic(row):
        return row.get("comic_id") or NO_COMIC_SENTINEL

    for e in tables.get("session_events", []):
        cid = _comic(e)
        comics.add(cid)
        chn = e.get("chapter_name")
        if chn:
            chapters.add((cid, chn))
        pid = e.get("page_id")
        if pid:
            prev = pages.get((cid, pid), (None, None))
            pages[(cid, pid)] = (chn or prev[0], e.get("page_title") or prev[1])

    for e in tables.get("page_interactions", []):
        cid = _comic(e)
        comics.add(cid)
        chn = e.get("chapter_name")
        if chn:
            chapters.add((cid, chn))
        pid = e.get("page_id")
        if pid:
            prev = pages.get((cid, pid), (None, None))
            pages[(cid, pid)] = (chn or prev[0], prev[1])

    for e in tables.get("app_launch_records", []):
        cid = _comic(e)
        comics.add(cid)
        chn = e.get("current_chapter")
        if chn:
            chapters.add((cid, chn))
        pid = e.get("current_page_id")
        if pid:
            prev = pages.get((cid, pid), (None, None))
            pages[(cid, pid)] = (chn or prev[0], prev[1])

    for a in tables.get("annotation_records", []):
        iid = a.get("image_id")
        if iid:
            cid = _comic(a)
            comics.add(cid)
            images.setdefault(iid, (cid, None))
    for t in tables.get("region_translations", []):
        iid = t.get("image_id")
        if iid:
            images.setdefault(iid, (None, None))

    # v5: session hierarchy aggregates also carry comic_id (and sometimes
    # chapter_name / page_id). Mine them so the catalog FKs hold even when
    # the event tables are empty.
    for s in tables.get("comic_sessions", []):
        cid = s.get("comic_id")
        if cid:
            comics.add(cid)
    for s in tables.get("chapter_sessions", []):
        cid = s.get("comic_id")
        chn = s.get("chapter_name")
        if cid:
            comics.add(cid)
            if chn:
                chapters.add((cid, chn))
    for s in tables.get("page_sessions", []):
        cid = s.get("comic_id")
        pid = s.get("page_id")
        if cid:
            comics.add(cid)
            if pid:
                pages.setdefault((cid, pid), (None, None))

    if comics:
        conn.executemany(
            "INSERT OR IGNORE INTO comics(comic_id, added_at) VALUES (?, ?)",
            [(c, _ms()) for c in comics])

    if chapters:
        conn.executemany(
            "INSERT OR IGNORE INTO chapters(comic_id, chapter_name) VALUES (?, ?)",
            list(chapters))

    if pages:
        conn.executemany(
            "INSERT OR IGNORE INTO pages(comic_id, page_id, chapter_name, page_title) VALUES (?, ?, ?, ?)",
            [(cid, pid, ch, pt) for (cid, pid), (ch, pt) in pages.items()])
        conn.executemany(
            """UPDATE pages
                  SET chapter_name = COALESCE(chapter_name, ?),
                      page_title   = COALESCE(page_title,   ?)
                WHERE comic_id = ? AND page_id = ?""",
            [(ch, pt, cid, pid) for (cid, pid), (ch, pt) in pages.items()])

    if images:
        conn.executemany(
            "INSERT OR IGNORE INTO images(image_id, comic_id, page_id) VALUES (?, ?, ?)",
            [(iid, cid, pid) for iid, (cid, pid) in images.items()])

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
             r.get("comic_id") or NO_COMIC_SENTINEL,
             r.get("chapter_name"), r.get("page_id"), r.get("page_title"),
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO session_events
             (device_id, user_id, local_id, event_type, timestamp, duration_ms,
              comic_id, chapter_name, page_id, page_title, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
             r.get("comic_id") or NO_COMIC_SENTINEL,
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO annotation_records
             (device_id, user_id, local_id, image_id, box_index,
              box_x, box_y, box_width, box_height,
              label, timestamp, tap_x, tap_y, region_type,
              parent_bubble_index, token_index, comic_id, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
             r.get("comic_id") or NO_COMIC_SENTINEL,
             r.get("chapter_name"), r.get("page_id"),
             r.get("normalized_x"), r.get("normalized_y"), r.get("hit_result"),
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO page_interactions
             (device_id, user_id, local_id, interaction_type, timestamp,
              comic_id, chapter_name, page_id, normalized_x, normalized_y, hit_result, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        data)
    return cur.rowcount

def _ingest_app_launches(conn, device_id, user_id, rows):
    if not rows:
        return 0
    data = [(device_id, user_id, r["local_id"],
             r["package_name"], r["timestamp"],
             r.get("comic_id") or NO_COMIC_SENTINEL,
             r.get("current_chapter"), r.get("current_page_id"),
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO app_launch_records
             (device_id, user_id, local_id, package_name, timestamp,
              comic_id, current_chapter, current_page_id, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

# ── session hierarchy inserters (v5) ──────────────────────────

def _ingest_app_sessions(conn, device_id, user_id, rows):
    if not rows:
        return 0
    data = [(device_id, user_id, r["local_id"],
             r["start_ts"], r.get("end_ts"), r.get("duration_ms"),
             r.get("app_version", ""),
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO app_sessions
             (device_id, user_id, local_id,
              start_ts, end_ts, duration_ms, app_version, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        data)
    return cur.rowcount

def _ingest_comic_sessions(conn, device_id, user_id, rows):
    if not rows:
        return 0
    data = [(device_id, user_id, r["local_id"],
             r["app_session_local_id"], r["comic_id"],
             r["start_ts"], r.get("end_ts"), r.get("duration_ms"),
             r.get("pages_read"),
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO comic_sessions
             (device_id, user_id, local_id,
              app_session_local_id, comic_id,
              start_ts, end_ts, duration_ms, pages_read, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        data)
    return cur.rowcount

def _ingest_chapter_sessions(conn, device_id, user_id, rows):
    if not rows:
        return 0
    data = [(device_id, user_id, r["local_id"],
             r["comic_session_local_id"], r["comic_id"], r["chapter_name"],
             r["start_ts"], r.get("end_ts"), r.get("duration_ms"),
             r.get("pages_visited"),
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO chapter_sessions
             (device_id, user_id, local_id,
              comic_session_local_id, comic_id, chapter_name,
              start_ts, end_ts, duration_ms, pages_visited, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        data)
    return cur.rowcount

def _force_close_orphans(conn, device_id):
    """Objective 24: close any session-hierarchy row whose end_ts is still
    NULL but has a strictly-newer sibling of the same type for this device.

    Runs AFTER all inserts in the current batch. Idempotent — re-running on
    an already-closed DB is a no-op because it only touches rows with
    end_ts IS NULL that have a newer sibling.

    Newer = a row with the same device_id AND strictly larger start_ts.
    The close_ts is the newer sibling's start_ts, so the orphan's
    duration_ms is set to (new.start_ts - orphan.start_ts). This matches
    the plan: "set end_ts = start_ts_of_new + 0".
    """
    # app_sessions / comic_sessions / chapter_sessions all share the
    # (start_ts, end_ts) shape. page_sessions uses (enter_ts, leave_ts).
    for table, start_col, end_col, dur_col in (
        ("app_sessions",     "start_ts", "end_ts",   "duration_ms"),
        ("comic_sessions",   "start_ts", "end_ts",   "duration_ms"),
        ("chapter_sessions", "start_ts", "end_ts",   "duration_ms"),
        ("page_sessions",    "enter_ts", "leave_ts", "dwell_ms"),
    ):
        conn.execute(f"""
            UPDATE {table}
               SET {end_col} = (
                       SELECT MIN(newer.{start_col})
                         FROM {table} AS newer
                        WHERE newer.device_id = {table}.device_id
                          AND newer.{start_col} > {table}.{start_col}
                   ),
                   {dur_col} = (
                       SELECT MIN(newer.{start_col})
                         FROM {table} AS newer
                        WHERE newer.device_id = {table}.device_id
                          AND newer.{start_col} > {table}.{start_col}
                   ) - {start_col},
                   close_reason = 'force_closed_by_new_session'
             WHERE device_id = ?
               AND {end_col} IS NULL
               AND EXISTS (
                   SELECT 1 FROM {table} AS newer
                    WHERE newer.device_id = {table}.device_id
                      AND newer.{start_col} > {table}.{start_col}
               )
        """, [device_id])

def _ingest_page_sessions(conn, device_id, user_id, rows):
    if not rows:
        return 0
    data = [(device_id, user_id, r["local_id"],
             r["chapter_session_local_id"], r["comic_id"], r["page_id"],
             r["enter_ts"], r.get("leave_ts"), r.get("dwell_ms"),
             r.get("interactions_n", 0),
             _b(r.get("synced", False)))
            for r in rows]
    cur = conn.executemany(
        """INSERT OR IGNORE INTO page_sessions
             (device_id, user_id, local_id,
              chapter_session_local_id, comic_id, page_id,
              enter_ts, leave_ts, dwell_ms, interactions_n, synced)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        data)
    return cur.rowcount

# ── main handler ──────────────────────────────────────────────

@job("ingest_unified_payload")
def _ingest_unified_payload(p):
    # Accept both shapes: nested under "unified_payload" (KMP Android client)
    # or flat at the top level (canonical dummy_load test clients).
    u = p.get("unified_payload") if isinstance(p.get("unified_payload"), dict) else p
    schema_version = u.get("schema_version")
    # v3 = pre-hierarchy (comic_id missing, treated as '_no_comic_')
    # v4 = comic_id present on event rows, no session hierarchy
    # v5 = session hierarchy aggregates (app/comic/chapter/page sessions)
    if schema_version not in (3, 4, 5):
        return {"accepted": False, "error": f"unsupported schema_version: {schema_version}"}
    mode = u.get("mode")
    if mode not in ("sync", "export"):
        return {"accepted": False, "error": f"invalid mode: {mode}"}
    device_id = u.get("device_id")
    if not device_id:
        return {"accepted": False, "error": "missing device_id"}

    user_id = u.get("user_id")
    app_version = u.get("app_version", "")
    export_ts = u.get("export_timestamp", 0)
    tables = u.get("tables") or {}
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
                # v5 session hierarchy
                "app_sessions":        _ingest_app_sessions(conn, device_id, user_id, tables.get("app_sessions", [])),
                "comic_sessions":      _ingest_comic_sessions(conn, device_id, user_id, tables.get("comic_sessions", [])),
                "chapter_sessions":    _ingest_chapter_sessions(conn, device_id, user_id, tables.get("chapter_sessions", [])),
                "page_sessions":       _ingest_page_sessions(conn, device_id, user_id, tables.get("page_sessions", [])),
            }
            # v5 objective 24: close-out policy for orphaned session rows.
            # Force-close any row whose end_ts/leave_ts is still NULL but
            # which has a strictly-newer sibling of the same type for the
            # same device. "Strictly newer" = start_ts > this row's start_ts.
            # The close_ts we write is the min start_ts of the newer sibling,
            # so duration_ms is at worst an overestimate that's still bounded
            # by reality.
            _force_close_orphans(conn, device_id)
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
