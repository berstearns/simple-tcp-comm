"""Shared receiver logic — admission control + archive insert.

Subclasses override deserialize_payload(flags, raw_bytes) → (cols, rows).
"""
import socket, sqlite3, os, sys, time, threading, shutil
sys.path.insert(0, os.path.dirname(__file__))
import protocol as P

ARCHIVE_DB = os.environ.get("ARCHIVE_DB", "/tmp/archive-receiver-test.db")
PORT = int(os.environ.get("ARCHIVE_PORT", "8080"))

# ── Admission control state ──────────────────────────────────
_lock = threading.Lock()
_active_inserts = 0
_last_insert_ms = 500  # start moderate

def _decide(payload_size, row_count, table_id, flags):
    disk_free = shutil.disk_usage(os.path.dirname(ARCHIVE_DB) or "/").free

    if disk_free < 100_000_000:
        return P.REJECT, P.REASON_DISK_FULL, 0, 0

    with _lock:
        if _active_inserts > 0:
            return P.REJECT, P.REASON_BUSY, 500, 500_000

    if payload_size > 10_000_000:
        return P.SHRINK, P.REASON_OK, 1000, 5_000_000

    if row_count > 10000:
        return P.SHRINK, P.REASON_OK, 5000, 5_000_000

    with _lock:
        lms = _last_insert_ms
    if lms > 2000:
        suggested = max(100, row_count // 2)
    elif lms < 200:
        suggested = min(10000, row_count * 2)
    else:
        suggested = row_count

    return P.ACCEPT, P.REASON_OK, suggested, 10_000_000

# ── Archive insert ───────────────────────────────────────────
def _init_archive():
    # archive_schema.sql lives at simple-tcp-comm/ (two levels up from variant subdirs, one from here)
    here = os.path.dirname(os.path.abspath(__file__))
    schema_path = os.path.join(os.path.dirname(here), "archive_schema.sql")
    db = sqlite3.connect(ARCHIVE_DB)
    with open(schema_path) as f:
        db.executescript(f.read())
    db.close()

def _insert_rows(table_name, cols, rows, worker_hash):
    global _active_inserts, _last_insert_ms

    with _lock:
        _active_inserts += 1

    t0 = time.monotonic()
    try:
        db = sqlite3.connect(ARCHIVE_DB)
        # use worker_hash as source_worker (short hex)
        source = f"worker-{worker_hash:04x}"
        acols = ["_source_worker"] + cols
        placeholders = ",".join(["?"] * len(acols))
        sql = f"INSERT OR IGNORE INTO {table_name} ({','.join(acols)}) VALUES ({placeholders})"

        before = db.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        db.executemany(sql, [(source,) + tuple(r) for r in rows])
        db.commit()
        after = db.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        db.close()

        inserted = after - before
        skipped = len(rows) - inserted
        return inserted, skipped
    finally:
        elapsed = int((time.monotonic() - t0) * 1000)
        with _lock:
            _active_inserts -= 1
            _last_insert_ms = elapsed

# ── Connection handler ───────────────────────────────────────
def handle_connection(conn, deserialize_fn):
    """Handle one worker connection. deserialize_fn(flags, raw, table_id) → (cols, rows)."""
    try:
        # Phase 1: read header
        hdr = P.recv_exact(conn, P.HEADER_SIZE)
        payload_size, row_count, table_id, flags, worker_hash = P.unpack_header(hdr)
        table_name = P.TABLE_NAMES[table_id] if table_id < len(P.TABLE_NAMES) else None

        if table_name is None:
            conn.sendall(P.pack_verdict(P.REJECT, P.REASON_OK, 0, 0))
            return

        # Phase 2: admission decision
        status, reason, max_rows, max_bytes = _decide(payload_size, row_count, table_id, flags)
        conn.sendall(P.pack_verdict(status, reason, max_rows, max_bytes))

        if status != P.ACCEPT:
            tag = {P.REJECT: "REJECT", P.SHRINK: "SHRINK"}[status]
            reason_str = {P.REASON_OK: "", P.REASON_BUSY: " busy", P.REASON_DISK_FULL: " disk_full", P.REASON_RATE_LIM: " rate_lim"}[reason]
            print(f"  {tag}{reason_str} table={table_name} rows={row_count} bytes={payload_size}")
            return

        # Phase 3: read payload
        raw = P.recv_exact(conn, payload_size)
        cols, rows = deserialize_fn(flags, raw, table_id)

        # Phase 4: insert
        inserted, skipped = _insert_rows(table_name, cols, rows, worker_hash)

        # adaptive suggestion for next batch
        with _lock:
            lms = _last_insert_ms
        if lms > 2000:
            next_rows = max(100, row_count // 2)
        elif lms < 200:
            next_rows = min(10000, row_count * 2)
        else:
            next_rows = row_count

        conn.sendall(P.pack_receipt(inserted, skipped, next_rows))
        print(f"  OK table={table_name} rows={row_count} inserted={inserted} skipped={skipped} ms={lms}")

    except (ConnectionError, struct.error) as e:
        print(f"  ERR: {e}")
    finally:
        conn.close()

# ── Server loop ──────────────────────────────────────────────
def serve(deserialize_fn, port=None):
    """Start the TCP archive receiver. Blocks forever."""
    port = port or PORT
    _init_archive()
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(16)
    print(f"archive receiver on :{port} (archive={ARCHIVE_DB})")
    try:
        while True:
            c, addr = s.accept()
            threading.Thread(target=handle_connection, args=(c, deserialize_fn), daemon=True).start()
    except KeyboardInterrupt:
        print("\nshutdown")
    finally:
        s.close()

# need struct for handle_connection error catch
import struct
