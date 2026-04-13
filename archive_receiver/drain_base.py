"""Shared drain loop logic — fetches cold rows from local worker DB and sends to archive receiver.

Subclasses override serialize_payload(cols, rows) → (flags, raw_bytes).
"""
import socket, sqlite3, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
import protocol as P

ARCHIVE_HOST = os.environ.get("ARCHIVE_HOST", "127.0.0.1")
ARCHIVE_PORT = int(os.environ.get("ARCHIVE_PORT", "8080"))
WORKER_DB = os.environ.get("WORKER_DB", "")
WORKER_NAME = os.environ.get("WORKER_NAME", "drain-worker")
DRAIN_INTERVAL = int(os.environ.get("DRAIN_INTERVAL", "300"))
COLD_AGE_MS = int(os.environ.get("COLD_AGE_MS", "3600000"))  # 1 hour

# ── Send one batch ───────────────────────────────────────────
def send_batch(table_id, table_name, cols, rows, serialize_fn):
    """Send a single batch to the archive receiver. Returns (inserted, skipped, next_max_rows) or None on failure."""
    flags, payload = serialize_fn(cols, rows)

    s = socket.socket()
    s.settimeout(30)
    try:
        s.connect((ARCHIVE_HOST, ARCHIVE_PORT))

        # Phase 1: header
        hdr = P.pack_header(len(payload), len(rows), table_id, flags, WORKER_NAME)
        s.sendall(hdr)

        # Phase 2: verdict
        verdict_raw = P.recv_exact(s, P.VERDICT_SIZE)
        status, reason, max_rows, max_bytes = P.unpack_verdict(verdict_raw)

        if status == P.REJECT:
            reason_str = {P.REASON_OK: "ok", P.REASON_BUSY: "busy", P.REASON_DISK_FULL: "disk_full", P.REASON_RATE_LIM: "rate_lim"}[reason]
            print(f"    REJECTED ({reason_str})")
            return None
        if status == P.SHRINK:
            print(f"    SHRINK → max_rows={max_rows} max_bytes={max_bytes}")
            return ("shrink", max_rows)

        # Phase 3: send payload (ACCEPT)
        s.sendall(payload)

        # Phase 4: receipt
        receipt_raw = P.recv_exact(s, P.RECEIPT_SIZE)
        inserted, skipped, next_max_rows = P.unpack_receipt(receipt_raw)
        return inserted, skipped, next_max_rows

    except (ConnectionError, TimeoutError, OSError) as e:
        print(f"    ERR: {e}")
        return None
    finally:
        s.close()

# ── Drain loop ───────────────────────────────────────────────
def drain_loop(serialize_fn, one_shot=False):
    """Main drain loop. Set one_shot=True for testing (runs once, no sleep)."""
    if not WORKER_DB:
        print("WORKER_DB not set")
        sys.exit(1)

    batch_rows = 500  # starting point, adapts from receiver feedback

    while True:
        print(f"\n--- drain cycle {time.strftime('%H:%M:%S')} (batch_rows={batch_rows}) ---")
        db = sqlite3.connect(f"file:{WORKER_DB}?mode=ro", uri=True)
        total_sent = 0

        for table_id, table_name in enumerate(P.TABLE_NAMES):
            # check table exists
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [table_name]
            ).fetchone()
            if not exists:
                continue

            # fetch cold rows
            if table_name in P.WATERMARK_TABLES:
                cur = db.execute(
                    f"SELECT * FROM {table_name} ORDER BY id LIMIT ?",
                    [batch_rows]
                )
            else:
                cur = db.execute(f"SELECT * FROM {table_name}")

            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()

            if not rows:
                continue

            result = send_batch(table_id, table_name, cols, rows, serialize_fn)

            if result is None:
                print(f"  {table_name}: receiver unavailable, stopping cycle")
                break

            if isinstance(result, tuple) and result[0] == "shrink":
                batch_rows = result[1]
                print(f"  {table_name}: shrink requested, new batch_rows={batch_rows}")
                continue

            inserted, skipped, next_max_rows = result
            total_sent += inserted
            batch_rows = next_max_rows
            print(f"  {table_name}: sent={len(rows)} inserted={inserted} skipped={skipped} next_batch={next_max_rows}")

        db.close()
        print(f"  total sent this cycle: {total_sent}")

        if one_shot:
            break

        print(f"  sleeping {DRAIN_INTERVAL}s...")
        time.sleep(DRAIN_INTERVAL)
