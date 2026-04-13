"""Shared binary protocol for archive receiver ↔ worker drain.

Wire format (all big-endian):

  HEADER  (worker → receiver, 16 bytes)
  ┌──────────────────┬──────────────────┬────────┬───────┬─────────┬──────────┐
  │ payload_size (4) │ row_count (4)    │ tid(1) │ fl(1) │ wh(2)   │ rsv(4)   │
  └──────────────────┴──────────────────┴────────┴───────┴─────────┴──────────┘

  VERDICT (receiver → worker, 12 bytes)
  ┌─────────┬─────────┬─────────┬──────────────────┬──────────────────┐
  │ stat(1) │ reas(1) │ pad(2)  │ max_rows (4)     │ max_bytes (4)    │
  └─────────┴─────────┴─────────┴──────────────────┴──────────────────┘

  PAYLOAD  (worker → receiver, payload_size bytes) — only if ACCEPT

  RECEIPT  (receiver → worker, 12 bytes)
  ┌──────────────────┬──────────────────┬──────────────────┐
  │ inserted (4)     │ skipped (4)      │ max_rows (4)     │
  └──────────────────┴──────────────────┴──────────────────┘
"""
import struct, hashlib

# ── Header ───────────────────────────────────────────────────
HEADER_FMT = "!II BB H I"   # 4+4+1+1+2+4 = 16 bytes
HEADER_SIZE = struct.calcsize(HEADER_FMT)
assert HEADER_SIZE == 16

def pack_header(payload_size, row_count, table_id, flags=0, worker_name=""):
    wh = int.from_bytes(hashlib.md5(worker_name.encode()).digest()[:2], "big")
    return struct.pack(HEADER_FMT, payload_size, row_count, table_id, flags, wh, 0)

def unpack_header(data):
    payload_size, row_count, table_id, flags, worker_hash, _rsv = struct.unpack(HEADER_FMT, data)
    return payload_size, row_count, table_id, flags, worker_hash

# ── Verdict ──────────────────────────────────────────────────
VERDICT_FMT = "!BB H I I"   # 1+1+2+4+4 = 12 bytes
VERDICT_SIZE = struct.calcsize(VERDICT_FMT)
assert VERDICT_SIZE == 12

ACCEPT = 0x01
REJECT = 0x02
SHRINK = 0x03

REASON_OK        = 0x00
REASON_BUSY      = 0x01
REASON_DISK_FULL = 0x02
REASON_RATE_LIM  = 0x03

def pack_verdict(status, reason=REASON_OK, max_rows=5000, max_bytes=10_000_000):
    return struct.pack(VERDICT_FMT, status, reason, 0, max_rows, max_bytes)

def unpack_verdict(data):
    status, reason, _pad, max_rows, max_bytes = struct.unpack(VERDICT_FMT, data)
    return status, reason, max_rows, max_bytes

# ── Receipt ──────────────────────────────────────────────────
RECEIPT_FMT = "!I I I"      # 4+4+4 = 12 bytes
RECEIPT_SIZE = struct.calcsize(RECEIPT_FMT)
assert RECEIPT_SIZE == 12

def pack_receipt(inserted, skipped, max_rows=5000):
    return struct.pack(RECEIPT_FMT, inserted, skipped, max_rows)

def unpack_receipt(data):
    inserted, skipped, max_rows = struct.unpack(RECEIPT_FMT, data)
    return inserted, skipped, max_rows

# ── Flags ────────────────────────────────────────────────────
FLAG_PLAIN       = 0x00
FLAG_ZLIB        = 0x01
FLAG_STRUCT_PACK = 0x02

# ── Table ID registry ────────────────────────────────────────
TABLE_NAMES = [
    "comics",              # 0
    "chapters",            # 1
    "pages",               # 2
    "images",              # 3
    "ingest_batches",      # 4
    "session_events",      # 5
    "annotation_records",  # 6
    "chat_messages",       # 7
    "page_interactions",   # 8
    "app_launch_records",  # 9
    "settings_changes",    # 10
    "region_translations", # 11
    "app_sessions",        # 12
    "comic_sessions",      # 13
    "chapter_sessions",    # 14
    "page_sessions",       # 15
]

TABLE_ID = {name: i for i, name in enumerate(TABLE_NAMES)}

# Tables with integer PK (watermarkable via WHERE id > ?)
WATERMARK_TABLES = {
    "ingest_batches", "session_events", "annotation_records",
    "chat_messages", "page_interactions", "app_launch_records",
    "settings_changes", "app_sessions", "comic_sessions",
    "chapter_sessions", "page_sessions",
}

# ── TCP helpers ──────────────────────────────────────────────
def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
    return buf
