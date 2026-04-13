#!/usr/bin/env python3
"""Worker drain — JSON plain (flags=0x00). No compression."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from protocol import FLAG_PLAIN
from drain_base import drain_loop

def serialize(cols, rows):
    raw = json.dumps({"cols": cols, "rows": rows}).encode()
    return FLAG_PLAIN, raw

if __name__ == "__main__":
    one_shot = "--once" in sys.argv
    print("variant: json_plain (flags=0x00)")
    drain_loop(serialize, one_shot=one_shot)
