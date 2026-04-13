#!/usr/bin/env python3
"""Worker drain — JSON + zlib (flags=0x01). Compressed payload."""
import sys, os, json, zlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from protocol import FLAG_ZLIB
from drain_base import drain_loop

def serialize(cols, rows):
    raw = zlib.compress(json.dumps({"cols": cols, "rows": rows}).encode())
    return FLAG_ZLIB, raw

if __name__ == "__main__":
    one_shot = "--once" in sys.argv
    print("variant: json_zlib (flags=0x01)")
    drain_loop(serialize, one_shot=one_shot)
