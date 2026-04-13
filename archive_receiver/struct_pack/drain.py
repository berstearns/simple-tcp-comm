#!/usr/bin/env python3
"""Worker drain — struct-packed binary rows (flags=0x02). Zero parsing overhead."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from protocol import FLAG_STRUCT_PACK
from drain_base import drain_loop
from schema_registry import SCHEMAS, encode_row

def serialize(cols, rows):
    # We need table_id — infer from cols by matching against SCHEMAS
    tid = None
    for t_id, (fmt, schema_cols) in SCHEMAS.items():
        if schema_cols == cols:
            tid = t_id
            break
    if tid is None:
        # fallback: try prefix match (cols from SELECT * might have extra)
        for t_id, (fmt, schema_cols) in SCHEMAS.items():
            if len(schema_cols) == len(cols):
                tid = t_id
                break
    if tid is None:
        raise ValueError(f"no schema match for cols={cols}")

    raw = b"".join(encode_row(tid, row) for row in rows)
    return FLAG_STRUCT_PACK, raw

if __name__ == "__main__":
    one_shot = "--once" in sys.argv
    print("variant: struct_pack (flags=0x02)")
    drain_loop(serialize, one_shot=one_shot)
