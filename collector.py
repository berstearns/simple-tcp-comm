#!/usr/bin/env python3
"""Offline collector — merges worker sqlite DBs into a consolidated archive.

Two modes:
  --direct PATH  Read worker DB files directly (same-machine only)
  --queue        Submit query jobs via the TCP queue (works across NAT)

Subcommands:
  collect   Incremental collection from a worker
  status    Show collection_log summary
  prune     Delete archived data older than N days
  verify    Compare archive row counts against worker DB

Zero non-stdlib dependencies. Requires Python 3.8+.
"""
import sqlite3, json, time, sys, os, uuid, argparse, pathlib

# ── Table registry ───────────────────────────────────────────
# Each entry: table_name -> {
#   "watermark": "id" | None   — column for incremental WHERE id > ? (None = full scan)
#   "ts_col":    str | None    — timestamp column for prune (None = never prune)
#   "unique_archive": tuple    — columns forming the UNIQUE constraint in the archive
#                                (always prefixed with _source_worker at INSERT time)
# }

TABLES = {
    # Catalog (no integer PK, always full-scan)
    "comics":              {"watermark": None, "ts_col": None,        "unique_archive": ("comic_id",)},
    "chapters":            {"watermark": None, "ts_col": None,        "unique_archive": ("comic_id", "chapter_name")},
    "pages":               {"watermark": None, "ts_col": None,        "unique_archive": ("comic_id", "page_id")},
    "images":              {"watermark": None, "ts_col": None,        "unique_archive": ("image_id",)},
    # Audit
    "ingest_batches":      {"watermark": "id", "ts_col": None,        "unique_archive": ("id",)},
    # Event tables
    "session_events":      {"watermark": "id", "ts_col": "timestamp", "unique_archive": ("device_id", "local_id")},
    "annotation_records":  {"watermark": "id", "ts_col": "timestamp", "unique_archive": ("device_id", "local_id")},
    "chat_messages":       {"watermark": "id", "ts_col": "timestamp", "unique_archive": ("device_id", "local_id")},
    "page_interactions":   {"watermark": "id", "ts_col": "timestamp", "unique_archive": ("device_id", "local_id")},
    "app_launch_records":  {"watermark": "id", "ts_col": "timestamp", "unique_archive": ("device_id", "local_id")},
    "settings_changes":    {"watermark": "id", "ts_col": "timestamp", "unique_archive": ("device_id", "local_id")},
    "region_translations": {"watermark": None, "ts_col": None,        "unique_archive": ("image_id", "bubble_index")},
    # Session hierarchy
    "app_sessions":        {"watermark": "id", "ts_col": "start_ts",  "unique_archive": ("device_id", "local_id")},
    "comic_sessions":      {"watermark": "id", "ts_col": "start_ts",  "unique_archive": ("device_id", "local_id")},
    "chapter_sessions":    {"watermark": "id", "ts_col": "start_ts",  "unique_archive": ("device_id", "local_id")},
    "page_sessions":       {"watermark": "id", "ts_col": "enter_ts",  "unique_archive": ("device_id", "local_id")},
}

BATCH_SIZE = 5000
POLL_INTERVAL = 2
POLL_TIMEOUT = 120

# ── Archive init ─────────────────────────────────────────────

def get_archive_path():
    return os.environ.get("ARCHIVE_DB", os.path.join(os.path.dirname(__file__), "archive.db"))

def init_archive(db_path):
    schema_path = os.path.join(os.path.dirname(__file__), "archive_schema.sql")
    conn = sqlite3.connect(db_path)
    with open(schema_path) as f:
        conn.executescript(f.read())
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

# ── Watermark tracking ───────────────────────────────────────

def get_last_watermark(archive, worker, table):
    row = archive.execute(
        "SELECT max_rowid FROM collection_log "
        "WHERE source_worker=? AND table_name=? AND max_rowid IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        [worker, table]
    ).fetchone()
    return row[0] if row else 0

def log_collection(archive, run_id, worker, table, rows_collected, rows_skipped,
                   max_rowid, duration_ms, db_path=None):
    archive.execute(
        "INSERT INTO collection_log "
        "(run_id, source_worker, source_db_path, table_name, rows_collected, "
        " rows_skipped, max_rowid, duration_ms) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [run_id, worker, db_path, table, rows_collected, rows_skipped,
         max_rowid, duration_ms]
    )

# ── Direct mode ──────────────────────────────────────────────

def collect_table_direct(archive, source, worker_name, table_name, run_id, watermark, db_path):
    meta = TABLES[table_name]
    t0 = time.monotonic()

    if meta["watermark"]:
        wm_col = meta["watermark"]
        cur = source.execute(f"SELECT * FROM {table_name} WHERE {wm_col} > ? ORDER BY {wm_col}", [watermark])
    else:
        cur = source.execute(f"SELECT * FROM {table_name}")

    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall()

    if not rows:
        dur = int((time.monotonic() - t0) * 1000)
        log_collection(archive, run_id, worker_name, table_name, 0, 0, watermark, dur, db_path)
        return 0, 0, watermark

    # find max id for watermark update
    new_max_rowid = watermark
    if meta["watermark"] and meta["watermark"] in cols:
        wm_idx = cols.index(meta["watermark"])
        new_max_rowid = max(row[wm_idx] for row in rows)

    # build INSERT OR IGNORE with _source_worker prepended
    archive_cols = ["_source_worker"] + cols
    placeholders = ",".join(["?"] * len(archive_cols))
    insert_sql = f"INSERT OR IGNORE INTO {table_name} ({','.join(archive_cols)}) VALUES ({placeholders})"

    before = archive.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    archive.executemany(insert_sql, [(worker_name,) + tuple(row) for row in rows])
    after = archive.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

    collected = after - before
    skipped = len(rows) - collected
    dur = int((time.monotonic() - t0) * 1000)
    log_collection(archive, run_id, worker_name, table_name, collected, skipped, new_max_rowid, dur, db_path)
    return collected, skipped, new_max_rowid

def collect_direct(db_path, worker_name, archive_path):
    print(f"collect (direct): {db_path}")
    print(f"archive: {archive_path}")
    print(f"worker:  {worker_name}")
    print()

    archive = init_archive(archive_path)
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    run_id = str(uuid.uuid4())[:8]
    total_collected = 0
    total_skipped = 0

    for table_name in TABLES:
        # check table exists in source
        exists = source.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table_name]
        ).fetchone()
        if not exists:
            print(f"  {table_name:25s}  SKIP (not in source)")
            continue

        watermark = get_last_watermark(archive, worker_name, table_name)
        collected, skipped, new_wm = collect_table_direct(
            archive, source, worker_name, table_name, run_id, watermark, db_path
        )
        total_collected += collected
        total_skipped += skipped
        status = f"{collected} new" + (f", {skipped} skipped" if skipped else "")
        print(f"  {table_name:25s}  {status}")

    archive.commit()
    archive.close()
    source.close()
    print(f"\nrun {run_id}: {total_collected} rows collected, {total_skipped} skipped")

# ── Queue mode ───────────────────────────────────────────────

def _import_client():
    """Import client.py from the same directory."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import client as c
    return c

def _wait_for_job(client, job_id, timeout=POLL_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.status(job_id)
        if resp.get("status") == "done":
            return resp.get("result")
        if resp.get("status") == "error" or not resp.get("ok", True):
            return {"error": resp.get("err", resp.get("result", "unknown"))}
        time.sleep(POLL_INTERVAL)
    return {"error": f"timeout after {timeout}s"}

def collect_table_queue(archive, client, worker_name, table_name, run_id, watermark, db_name):
    meta = TABLES[table_name]
    t0 = time.monotonic()

    if meta["watermark"]:
        wm_col = meta["watermark"]
        sql = f"SELECT * FROM {table_name} WHERE {wm_col} > ? ORDER BY {wm_col} LIMIT {BATCH_SIZE}"
        params = [watermark]
    else:
        sql = f"SELECT * FROM {table_name}"
        params = []

    total_collected = 0
    total_skipped = 0
    current_watermark = watermark

    while True:
        resp = client.submit({"task": "query", "db": db_name, "sql": sql, "params": params})
        if not resp.get("ok"):
            print(f"    submit failed: {resp}")
            break
        job_id = resp["id"]
        result = _wait_for_job(client, job_id)

        if "error" in result:
            print(f"    query failed: {result['error']}")
            break

        cols = result.get("cols", [])
        rows = result.get("rows", [])

        if not rows:
            break

        # update watermark
        if meta["watermark"] and meta["watermark"] in cols:
            wm_idx = cols.index(meta["watermark"])
            current_watermark = max(row[wm_idx] for row in rows)

        archive_cols = ["_source_worker"] + cols
        placeholders = ",".join(["?"] * len(archive_cols))
        insert_sql = f"INSERT OR IGNORE INTO {table_name} ({','.join(archive_cols)}) VALUES ({placeholders})"

        before = archive.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        archive.executemany(insert_sql, [(worker_name,) + tuple(row) for row in rows])
        after = archive.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

        batch_collected = after - before
        batch_skipped = len(rows) - batch_collected
        total_collected += batch_collected
        total_skipped += batch_skipped

        # if not paginated (no watermark) or got fewer than BATCH_SIZE, done
        if not meta["watermark"] or len(rows) < BATCH_SIZE:
            break

        # next page
        params = [current_watermark]

    dur = int((time.monotonic() - t0) * 1000)
    log_collection(archive, run_id, worker_name, table_name,
                   total_collected, total_skipped, current_watermark, dur)
    return total_collected, total_skipped, current_watermark

def collect_queue(worker_name, archive_path, db_name="app7"):
    client = _import_client()
    print(f"collect (queue): db={db_name}")
    print(f"archive: {archive_path}")
    print(f"worker:  {worker_name}")
    print()

    archive = init_archive(archive_path)
    run_id = str(uuid.uuid4())[:8]
    total_collected = 0
    total_skipped = 0

    for table_name in TABLES:
        watermark = get_last_watermark(archive, worker_name, table_name)
        collected, skipped, _ = collect_table_queue(
            archive, client, worker_name, table_name, run_id, watermark, db_name
        )
        total_collected += collected
        total_skipped += skipped
        status = f"{collected} new" + (f", {skipped} skipped" if skipped else "")
        print(f"  {table_name:25s}  {status}")

    archive.commit()
    archive.close()
    print(f"\nrun {run_id}: {total_collected} rows collected, {total_skipped} skipped")

# ── Status ───────────────────────────────────────────────────

def show_status(archive_path):
    if not os.path.exists(archive_path):
        print(f"archive not found: {archive_path}")
        sys.exit(1)

    db = sqlite3.connect(archive_path)
    db.row_factory = sqlite3.Row

    # last run
    last = db.execute(
        "SELECT run_id, collected_at FROM collection_log ORDER BY id DESC LIMIT 1"
    ).fetchone()

    print(f"Archive: {archive_path}")
    if last:
        print(f"Last collection: {last['collected_at']}")
        print(f"Run: {last['run_id']}")
    else:
        print("No collections recorded.")
        db.close()
        return

    # per-worker summary
    workers = db.execute(
        "SELECT DISTINCT source_worker FROM collection_log ORDER BY source_worker"
    ).fetchall()

    for w in workers:
        wn = w["source_worker"]
        print(f"\nWorker: {wn}")
        rows = db.execute(
            "SELECT cl.table_name, cl.rows_collected, cl.rows_skipped, cl.max_rowid, cl.collected_at "
            "FROM collection_log cl "
            "INNER JOIN (SELECT table_name, MAX(id) AS max_id FROM collection_log "
            "            WHERE source_worker=? GROUP BY table_name) latest "
            "ON cl.table_name = latest.table_name AND cl.id = latest.max_id "
            "ORDER BY cl.table_name",
            [wn]
        ).fetchall()
        for r in rows:
            skip = f" ({r['rows_skipped']} skipped)" if r["rows_skipped"] else ""
            wm = f"  wm={r['max_rowid']}" if r["max_rowid"] else ""
            print(f"  {r['table_name']:25s}  {r['rows_collected']:>5d} rows{skip}{wm}")

    # archive row counts
    print("\nArchive totals:")
    for table_name in TABLES:
        try:
            n = db.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            if n > 0:
                print(f"  {table_name:25s}  {n:>7d}")
        except sqlite3.OperationalError:
            pass

    db.close()

# ── Prune ────────────────────────────────────────────────────

def prune_archive(archive_path, days):
    if not os.path.exists(archive_path):
        print(f"archive not found: {archive_path}")
        sys.exit(1)

    cutoff_ms = int((time.time() - days * 86400) * 1000)
    db = sqlite3.connect(archive_path)
    total = 0

    print(f"Pruning rows older than {days} days (cutoff timestamp: {cutoff_ms})")
    for table_name, meta in TABLES.items():
        ts_col = meta["ts_col"]
        if ts_col is None:
            continue
        try:
            cur = db.execute(f"DELETE FROM {table_name} WHERE {ts_col} < ?", [cutoff_ms])
            if cur.rowcount > 0:
                print(f"  {table_name:25s}  {cur.rowcount} rows pruned")
                total += cur.rowcount
        except sqlite3.OperationalError:
            pass

    db.commit()
    db.close()
    print(f"\nTotal: {total} rows pruned")

# ── Verify ───────────────────────────────────────────────────

def verify_direct(archive_path, source_path, worker_name):
    if not os.path.exists(archive_path):
        print(f"archive not found: {archive_path}")
        sys.exit(1)
    if not os.path.exists(source_path):
        print(f"source not found: {source_path}")
        sys.exit(1)

    archive = sqlite3.connect(archive_path)
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)

    print(f"Verify: archive vs worker (direct)")
    print(f"  archive: {archive_path}")
    print(f"  worker:  {source_path}")
    print(f"  name:    {worker_name}")
    print()

    total = 0
    matched = 0

    for table_name in TABLES:
        # check source has the table
        exists = source.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table_name]
        ).fetchone()
        if not exists:
            print(f"  {table_name:25s}  SKIP (not in worker)")
            continue

        total += 1
        w_count = source.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        a_count = archive.execute(
            f"SELECT COUNT(*) FROM {table_name} WHERE _source_worker=?", [worker_name]
        ).fetchone()[0]

        ok = w_count == a_count
        if ok:
            matched += 1
        tag = "OK" if ok else "MISMATCH"
        print(f"  {table_name:25s}  worker={w_count:<7d}  archive={a_count:<7d}  {tag}")

    print(f"\nOVERALL: {'PASS' if matched == total else 'FAIL'} ({matched}/{total} tables match)")

    archive.close()
    source.close()
    sys.exit(0 if matched == total else 1)

# ── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Offline collector — merge worker DBs into archive"
    )
    sub = parser.add_subparsers(dest="command")

    # collect
    p_collect = sub.add_parser("collect", help="Collect data from a worker")
    mode = p_collect.add_mutually_exclusive_group(required=True)
    mode.add_argument("--direct", metavar="PATH", help="Path to worker sqlite DB")
    mode.add_argument("--queue", action="store_true", help="Collect via TCP queue")
    p_collect.add_argument("--worker-name", required=True, help="Worker identifier for _source_worker")
    p_collect.add_argument("--db", default="app7", help="DB name for queue mode (default: app7)")

    # status
    sub.add_parser("status", help="Show collection summary")

    # prune
    p_prune = sub.add_parser("prune", help="Delete old archived data")
    p_prune.add_argument("--days", type=int, required=True, help="Delete data older than N days")

    # verify
    p_verify = sub.add_parser("verify", help="Compare archive vs worker row counts")
    p_verify.add_argument("--direct", metavar="PATH", required=True, help="Path to worker sqlite DB")
    p_verify.add_argument("--worker-name", required=True, help="Worker name to filter archive rows")

    args = parser.parse_args()
    archive_path = get_archive_path()

    if args.command == "collect":
        if args.direct:
            collect_direct(args.direct, args.worker_name, archive_path)
        else:
            collect_queue(args.worker_name, archive_path, args.db)
    elif args.command == "status":
        show_status(archive_path)
    elif args.command == "prune":
        prune_archive(archive_path, args.days)
    elif args.command == "verify":
        verify_direct(archive_path, args.direct, args.worker_name)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
