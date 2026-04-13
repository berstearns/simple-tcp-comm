#!/usr/bin/env python3
"""Archive receiver — JSON + zlib (flags=0x01). Compressed payload."""
import sys, os, json, zlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from receiver_base import serve

def deserialize(flags, raw, table_id):
    data = json.loads(zlib.decompress(raw))
    return data["cols"], data["rows"]

if __name__ == "__main__":
    print("variant: json_zlib (flags=0x01)")
    serve(deserialize)
