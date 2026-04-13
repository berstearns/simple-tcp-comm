"""Fixed struct schemas per table_id for binary serialization.

Each entry: table_id → (struct_fmt, col_names, str_field_indices)

String fields use fixed-width bytes (padded with \\x00).
Integers and reals use native struct types.
NULL is encoded as: 0 for ints, 0.0 for reals, b'\\x00'*N for strings.

String widths are generous to avoid truncation:
  - 64 bytes for page_id, image_id, page_title, label, text
  - 128 bytes for row_counts (JSON blob in ingest_batches)
  - 32 bytes for most identifiers
"""
import struct

# field size constants
S16  = "16s"
S32  = "32s"
S64  = "64s"
S128 = "128s"
S256 = "256s"

# (struct_format, column_names)
# Format: ! = big-endian, I = uint32, i = int32, q = int64, Q = uint64, d = double, Ns = N-byte string
SCHEMAS = {
    # 0: comics (comic_id TEXT, display_name TEXT, added_at INTEGER)
    0: ("!" + S32 + S64 + "q",
        ["comic_id", "display_name", "added_at"]),

    # 1: chapters (comic_id TEXT, chapter_name TEXT)
    1: ("!" + S32 + S64,
        ["comic_id", "chapter_name"]),

    # 2: pages (comic_id TEXT, page_id TEXT, chapter_name TEXT, page_title TEXT)
    2: ("!" + S32 + S64 + S64 + S64,
        ["comic_id", "page_id", "chapter_name", "page_title"]),

    # 3: images (image_id TEXT, comic_id TEXT, page_id TEXT)
    3: ("!" + S64 + S32 + S64,
        ["image_id", "comic_id", "page_id"]),

    # 4: ingest_batches (id INT, schema_version INT, mode TEXT, device_id TEXT, user_id TEXT,
    #    app_version TEXT, export_timestamp INT, ingested_at INT, row_counts TEXT)
    4: ("!" + "i" + "i" + S16 + S32 + S32 + S32 + "q" + "q" + S256,
        ["id", "schema_version", "mode", "device_id", "user_id",
         "app_version", "export_timestamp", "ingested_at", "row_counts"]),

    # 5: session_events (id INT, device_id TEXT, user_id TEXT, local_id INT,
    #    event_type TEXT, timestamp INT, duration_ms INT, comic_id TEXT,
    #    chapter_name TEXT, page_id TEXT, page_title TEXT, synced INT)
    5: ("!" + "i" + S32 + S32 + "i" + S32 + "q" + "i" + S32 + S64 + S64 + S64 + "i",
        ["id", "device_id", "user_id", "local_id",
         "event_type", "timestamp", "duration_ms", "comic_id",
         "chapter_name", "page_id", "page_title", "synced"]),

    # 6: annotation_records (id INT, device_id TEXT, user_id TEXT, local_id INT,
    #    image_id TEXT, box_index INT, box_x REAL, box_y REAL, box_width REAL, box_height REAL,
    #    label TEXT, timestamp INT, tap_x REAL, tap_y REAL, region_type TEXT,
    #    parent_bubble_index INT, token_index INT, comic_id TEXT, synced INT)
    6: ("!" + "i" + S32 + S32 + "i" + S64 + "i" + "d" + "d" + "d" + "d"
         + S64 + "q" + "d" + "d" + S16 + "i" + "i" + S32 + "i",
        ["id", "device_id", "user_id", "local_id",
         "image_id", "box_index", "box_x", "box_y", "box_width", "box_height",
         "label", "timestamp", "tap_x", "tap_y", "region_type",
         "parent_bubble_index", "token_index", "comic_id", "synced"]),

    # 7: chat_messages (id INT, device_id TEXT, user_id TEXT, local_id INT,
    #    sender TEXT, text TEXT, timestamp INT, synced INT)
    7: ("!" + "i" + S32 + S32 + "i" + S32 + S256 + "q" + "i",
        ["id", "device_id", "user_id", "local_id",
         "sender", "text", "timestamp", "synced"]),

    # 8: page_interactions (id INT, device_id TEXT, user_id TEXT, local_id INT,
    #    interaction_type TEXT, timestamp INT, comic_id TEXT, chapter_name TEXT,
    #    page_id TEXT, normalized_x REAL, normalized_y REAL, hit_result TEXT, synced INT)
    8: ("!" + "i" + S32 + S32 + "i" + S32 + "q" + S32 + S64 + S64 + "d" + "d" + S32 + "i",
        ["id", "device_id", "user_id", "local_id",
         "interaction_type", "timestamp", "comic_id", "chapter_name",
         "page_id", "normalized_x", "normalized_y", "hit_result", "synced"]),

    # 9: app_launch_records (id INT, device_id TEXT, user_id TEXT, local_id INT,
    #    package_name TEXT, timestamp INT, comic_id TEXT, current_chapter TEXT,
    #    current_page_id TEXT, synced INT)
    9: ("!" + "i" + S32 + S32 + "i" + S64 + "q" + S32 + S64 + S64 + "i",
        ["id", "device_id", "user_id", "local_id",
         "package_name", "timestamp", "comic_id", "current_chapter",
         "current_page_id", "synced"]),

    # 10: settings_changes (id INT, device_id TEXT, user_id TEXT, local_id INT,
    #     setting_key TEXT, old_value TEXT, new_value TEXT, timestamp INT, synced INT)
    10: ("!" + "i" + S32 + S32 + "i" + S64 + S64 + S64 + "q" + "i",
         ["id", "device_id", "user_id", "local_id",
          "setting_key", "old_value", "new_value", "timestamp", "synced"]),

    # 11: region_translations (id TEXT, device_id TEXT, user_id TEXT,
    #     image_id TEXT, bubble_index INT, original_text TEXT, meaning_translation TEXT,
    #     literal_translation TEXT, source_language TEXT, target_language TEXT)
    11: ("!" + S64 + S32 + S32 + S64 + "i" + S256 + S256 + S256 + S16 + S16,
         ["id", "device_id", "user_id",
          "image_id", "bubble_index", "original_text", "meaning_translation",
          "literal_translation", "source_language", "target_language"]),

    # 12: app_sessions (id INT, device_id TEXT, user_id TEXT, local_id INT,
    #     start_ts INT, end_ts INT, duration_ms INT, app_version TEXT, close_reason TEXT, synced INT)
    12: ("!" + "i" + S32 + S32 + "i" + "q" + "q" + "i" + S32 + S32 + "i",
         ["id", "device_id", "user_id", "local_id",
          "start_ts", "end_ts", "duration_ms", "app_version", "close_reason", "synced"]),

    # 13: comic_sessions (id INT, device_id TEXT, user_id TEXT, local_id INT,
    #     app_session_local_id INT, comic_id TEXT, start_ts INT, end_ts INT,
    #     duration_ms INT, pages_read INT, close_reason TEXT, synced INT)
    13: ("!" + "i" + S32 + S32 + "i" + "i" + S32 + "q" + "q" + "i" + "i" + S32 + "i",
         ["id", "device_id", "user_id", "local_id",
          "app_session_local_id", "comic_id", "start_ts", "end_ts",
          "duration_ms", "pages_read", "close_reason", "synced"]),

    # 14: chapter_sessions (id INT, device_id TEXT, user_id TEXT, local_id INT,
    #     comic_session_local_id INT, comic_id TEXT, chapter_name TEXT,
    #     start_ts INT, end_ts INT, duration_ms INT, pages_visited INT, close_reason TEXT, synced INT)
    14: ("!" + "i" + S32 + S32 + "i" + "i" + S32 + S64 + "q" + "q" + "i" + "i" + S32 + "i",
         ["id", "device_id", "user_id", "local_id",
          "comic_session_local_id", "comic_id", "chapter_name",
          "start_ts", "end_ts", "duration_ms", "pages_visited", "close_reason", "synced"]),

    # 15: page_sessions (id INT, device_id TEXT, user_id TEXT, local_id INT,
    #     chapter_session_local_id INT, comic_id TEXT, page_id TEXT,
    #     enter_ts INT, leave_ts INT, dwell_ms INT, interactions_n INT, close_reason TEXT, synced INT)
    15: ("!" + "i" + S32 + S32 + "i" + "i" + S32 + S64 + "q" + "q" + "i" + "i" + S32 + "i",
         ["id", "device_id", "user_id", "local_id",
          "chapter_session_local_id", "comic_id", "page_id",
          "enter_ts", "leave_ts", "dwell_ms", "interactions_n", "close_reason", "synced"]),
}

def _is_str_field(fmt_char):
    return fmt_char.endswith("s")

def _parse_fields(fmt):
    """Parse struct format into list of (format_char, is_string, byte_width)."""
    # strip endian prefix
    f = fmt.lstrip("!<>=@")
    fields = []
    i = 0
    while i < len(f):
        if f[i].isdigit():
            j = i
            while j < len(f) and f[j].isdigit():
                j += 1
            n = int(f[i:j])
            ch = f[j]
            fields.append((f"{n}{ch}", ch == "s", n if ch == "s" else struct.calcsize(f"!{n}{ch}")))
            i = j + 1
        else:
            fields.append((f[i], False, struct.calcsize(f"!{f[i]}")))
            i += 1
    return fields

def encode_row(table_id, row):
    """Encode a sqlite row (tuple) to struct bytes. NULLs become zero/empty."""
    fmt, col_names = SCHEMAS[table_id]
    fields = _parse_fields(fmt)
    values = []
    for i, (fc, is_str, width) in enumerate(fields):
        val = row[i]
        if is_str:
            s = str(val) if val is not None else ""
            values.append(s.encode("utf-8")[:width].ljust(width, b"\x00"))
        elif "d" in fc:
            values.append(float(val) if val is not None else 0.0)
        else:
            values.append(int(val) if val is not None else 0)
    return struct.pack(fmt, *values)

def decode_row(table_id, raw, offset=0):
    """Decode struct bytes back to a tuple of Python values. Strips null-padding from strings."""
    fmt, col_names = SCHEMAS[table_id]
    row_size = struct.calcsize(fmt)
    values = struct.unpack(fmt, raw[offset:offset + row_size])
    fields = _parse_fields(fmt)
    result = []
    for i, (fc, is_str, width) in enumerate(fields):
        if is_str:
            decoded = values[i].rstrip(b"\x00").decode("utf-8")
            result.append(decoded if decoded else None)
        elif "d" in fc:
            # reals: keep 0.0 as 0.0, only None if it was genuinely null
            result.append(values[i])
        else:
            # ints: keep 0 as 0 — don't convert to None
            result.append(values[i])
    return tuple(result)

def row_size(table_id):
    return struct.calcsize(SCHEMAS[table_id][0])
