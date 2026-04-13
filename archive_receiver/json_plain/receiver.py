#!/usr/bin/env python3
"""Archive receiver — JSON plain (flags=0x00). No compression."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from receiver_base import serve

def deserialize(flags, raw, table_id):
    data = json.loads(raw)
    return data["cols"], data["rows"]

if __name__ == "__main__":
    print("variant: json_plain (flags=0x00)")
    serve(deserialize)
