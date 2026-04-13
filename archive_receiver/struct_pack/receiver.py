#!/usr/bin/env python3
"""Archive receiver — struct-packed binary rows (flags=0x02). Zero parsing overhead."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from receiver_base import serve
from protocol import TABLE_NAMES
from schema_registry import SCHEMAS, decode_row, row_size

def deserialize(flags, raw, table_id):
    tid = table_id
    fmt, col_names = SCHEMAS[tid]
    rs = row_size(tid)
    rows = []
    for i in range(0, len(raw), rs):
        rows.append(decode_row(tid, raw, i))
    return col_names, rows

if __name__ == "__main__":
    print("variant: struct_pack (flags=0x02)")
    serve(deserialize)
