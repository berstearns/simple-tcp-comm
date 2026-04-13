#!/usr/bin/env python3
"""Generate archive drain flow diagram for TCP :8080 binary protocol.

Shows: Worker drain.py → cold row selection → HEADER → VERDICT →
PAYLOAD → RECEIPT → prune cycle. Full binary protocol detail.
"""
import json
import sys

elements = []
_counter = [0]

def nid():
    _counter[0] += 1
    return f"elem_{_counter[0]:04d}"

def idx():
    return f"a{_counter[0]:04d}"

BASE = {
    "version": 1, "isDeleted": False, "fillStyle": "solid",
    "strokeWidth": 2, "strokeStyle": "solid", "roughness": 1,
    "opacity": 100, "angle": 0, "strokeColor": "#1e1e1e",
    "groupIds": [], "frameId": None, "boundElements": [],
    "updated": 1775829200000, "link": None, "locked": False,
}

def rect(x, y, w, h, color, label=None, font_size=14, rounded=True, label_color=None):
    rid = nid()
    r = dict(BASE)
    r.update({
        "type": "rectangle", "versionNonce": _counter[0] * 13 + 1,
        "index": idx(), "id": rid,
        "x": float(x), "y": float(y),
        "width": float(w), "height": float(h),
        "backgroundColor": color, "seed": 10000 + _counter[0],
        "roundness": {"type": 3} if rounded else None,
        "boundElements": [],
    })
    elements.append(r)
    if label is not None:
        lines = label.count("\n") + 1
        text_h = font_size * 1.25 * lines
        tid = nid()
        t = dict(BASE)
        t.update({
            "type": "text", "versionNonce": _counter[0] * 17 + 1,
            "index": idx(), "id": tid,
            "x": float(x + 1), "y": float(y + (h - text_h) / 2),
            "width": float(w - 2), "height": float(text_h),
            "backgroundColor": "transparent", "seed": 20000 + _counter[0],
            "roundness": None, "fontSize": font_size, "fontFamily": 5,
            "text": label, "textAlign": "center", "verticalAlign": "middle",
            "containerId": rid, "originalText": label,
            "autoResize": True, "lineHeight": 1.25,
        })
        if label_color:
            t["strokeColor"] = label_color
        elements.append(t)
        r["boundElements"] = [{"id": tid, "type": "text"}]
    return rid

def text(x, y, label, font_size=12, align="left", color="#1e1e1e"):
    rid = nid()
    w = max(len(label) * font_size * 0.6, 20)
    h = font_size * 1.25
    t = dict(BASE)
    t.update({
        "type": "text", "versionNonce": _counter[0] * 19 + 1,
        "index": idx(), "id": rid,
        "x": float(x), "y": float(y),
        "width": float(w), "height": float(h),
        "backgroundColor": "transparent", "seed": 30000 + _counter[0],
        "roundness": None, "fontSize": font_size, "fontFamily": 5,
        "text": label, "textAlign": align, "verticalAlign": "top",
        "containerId": None, "originalText": label,
        "autoResize": True, "lineHeight": 1.25, "strokeColor": color,
    })
    elements.append(t)
    return rid

def arrow(x1, y1, x2, y2, dashed=False):
    rid = nid()
    a = dict(BASE)
    a.update({
        "type": "arrow", "versionNonce": _counter[0] * 23 + 1,
        "index": idx(), "id": rid,
        "x": float(x1), "y": float(y1),
        "width": float(abs(x2 - x1)), "height": float(abs(y2 - y1)),
        "backgroundColor": "transparent", "seed": 40000 + _counter[0],
        "roundness": {"type": 2},
        "points": [[0.0, 0.0], [float(x2 - x1), float(y2 - y1)]],
        "lastCommittedPoint": None,
        "startBinding": None, "endBinding": None,
        "startArrowhead": None, "endArrowhead": "arrow", "elbowed": False,
    })
    if dashed:
        a["strokeStyle"] = "dashed"
    elements.append(a)
    return rid

BLUE     = "#a5d8ff"
YELLOW   = "#ffec99"
PEACH    = "#ffd8a8"
RED      = "#ffc9c9"
GREEN    = "#b2f2bb"
LAVENDER = "#e8deee"
GRAY     = "#495057"
FRAME    = "#868e96"

# Two-column layout: Worker (left), Receiver (right), protocol in middle
LEFT_CX = 300   # worker column
RIGHT_CX = 900  # receiver column
MID_CX = 600    # protocol exchange center

# ============================================================
# TITLE
# ============================================================
text(100, 10, "Archive Drain Flow — TCP :8080 Binary Protocol", font_size=24)
text(100, 50, "Worker drain.py → Neptune archive_receiver.py · Admission control · Adaptive batching", font_size=16)
text(100, 76, "HEADER (16B) → VERDICT → PAYLOAD (JSON/zlib/struct) → RECEIPT → Prune confirmed", font_size=13)

# ============================================================
# Column headers
# ============================================================
text(LEFT_CX - 60, 120, "Worker (drain.py)", font_size=16, color=FRAME)
text(RIGHT_CX - 80, 120, "Archive Receiver", font_size=16, color=FRAME)

# Vertical lane dividers (dashed)
arrow(600, 140, 600, 1350, dashed=True)
elements[-1]["endArrowhead"] = None

# ============================================================
# STEP 1: Drain timer fires
# ============================================================
Y = 160
rect(LEFT_CX - 170, Y, 340, 45, RED,
     "Drain timer fires (every 300s)", font_size=13)
text(LEFT_CX + 180, Y + 14, "configurable interval", font_size=10, color=GRAY)

arrow(LEFT_CX, Y + 45, LEFT_CX, Y + 65)

# ============================================================
# STEP 2: Select cold rows
# ============================================================
Y += 70
rect(LEFT_CX - 170, Y, 340, 55, PEACH,
     "SELECT cold rows from app7.db\nWHERE updated_at < NOW() - 1hr", font_size=12)
text(LEFT_CX + 180, Y + 10, "batch by table_id", font_size=10, color=GRAY)
text(LEFT_CX + 180, Y + 24, "respect batch_size limit", font_size=10, color=GRAY)

arrow(LEFT_CX, Y + 55, LEFT_CX, Y + 75)

# ============================================================
# STEP 3: TCP connect
# ============================================================
Y += 80
rect(LEFT_CX - 140, Y, 280, 40, RED,
     "TCP connect → Neptune :8080", font_size=13)

arrow(LEFT_CX + 140, Y + 20, RIGHT_CX - 140, Y + 20)
text(MID_CX - 40, Y + 2, "TCP :8080", font_size=11, color=GRAY)

# ============================================================
# STEP 4: Send HEADER
# ============================================================
Y += 70
rect(LEFT_CX - 170, Y, 340, 65, LAVENDER,
     "Send HEADER (16 bytes)\npayload_size (4B) | row_count (4B)\ntable_id (4B) | flags (4B)", font_size=12)

arrow(LEFT_CX + 170, Y + 32, RIGHT_CX - 170, Y + 32)
text(MID_CX - 30, Y + 14, "16 bytes →", font_size=11, color=GRAY)

# Receiver processes header
rect(RIGHT_CX - 160, Y, 320, 65, GREEN,
     "Parse HEADER\nCheck table_id valid\nEvaluate admission control", font_size=12)

# ============================================================
# STEP 5: Receive VERDICT
# ============================================================
Y += 95
rect(RIGHT_CX - 160, Y, 320, 65, YELLOW,
     "Send VERDICT back\nACCEPT / REJECT / SHRINK\n+ adjusted batch_size", font_size=12)

arrow(RIGHT_CX - 160, Y + 32, LEFT_CX + 170, Y + 32)
text(MID_CX - 30, Y + 14, "← verdict", font_size=11, color=GRAY)

rect(LEFT_CX - 170, Y, 340, 65, RED,
     "Receive VERDICT\nIf REJECT: abort, retry later\nIf SHRINK: reduce batch", font_size=12)

# Verdict detail on the right
VD_Y = Y + 75
rect(RIGHT_CX - 130, VD_Y, 120, 35, GREEN, "ACCEPT", font_size=12)
rect(RIGHT_CX - 130 + 130, VD_Y, 120, 35, YELLOW, "REJECT", font_size=12)
rect(RIGHT_CX - 130 + 260, VD_Y, 120, 35, YELLOW, "SHRINK", font_size=12)
text(RIGHT_CX - 130, VD_Y + 40, "proceed as-is", font_size=10, color=GRAY)
text(RIGHT_CX, VD_Y + 40, "back off", font_size=10, color=GRAY)
text(RIGHT_CX + 130, VD_Y + 40, "reduce N", font_size=10, color=GRAY)

# ============================================================
# STEP 6: Send PAYLOAD
# ============================================================
Y += 130
rect(LEFT_CX - 170, Y, 340, 65, LAVENDER,
     "Send PAYLOAD\nformat determined by flags byte\n(JSON / JSON+zlib / struct-pack)", font_size=12)

arrow(LEFT_CX + 170, Y + 32, RIGHT_CX - 170, Y + 32)
text(MID_CX - 40, Y + 14, "payload →", font_size=11, color=GRAY)

rect(RIGHT_CX - 160, Y, 320, 65, GREEN,
     "Receive PAYLOAD\nDecompress if zlib\nDeserialize rows", font_size=12)

# Format options below
FMT_Y = Y + 80
rect(LEFT_CX - 200, FMT_Y, 160, 40, LAVENDER, "0x00: JSON plain", font_size=11)
rect(LEFT_CX - 30, FMT_Y, 180, 40, LAVENDER, "0x01: JSON+zlib\n(3-6× compression)", font_size=10)
rect(LEFT_CX + 160, FMT_Y, 170, 40, LAVENDER, "0x02: struct-pack\n(binary, fastest)", font_size=10)
text(LEFT_CX - 200, FMT_Y + 44, "flags byte determines wire format", font_size=10, color=GRAY)

# ============================================================
# STEP 7: INSERT into archive
# ============================================================
Y += 140
rect(RIGHT_CX - 160, Y, 320, 55, PEACH,
     "INSERT OR IGNORE into archive\n_source_worker + UNIQUE dedup", font_size=12)
text(RIGHT_CX + 170, Y + 10, "idempotent", font_size=10, color=GRAY)
text(RIGHT_CX + 170, Y + 24, "skip duplicates", font_size=10, color=GRAY)

arrow(RIGHT_CX, Y - 10, RIGHT_CX, Y)

# ============================================================
# STEP 8: Send RECEIPT
# ============================================================
Y += 80
rect(RIGHT_CX - 160, Y, 320, 55, GREEN,
     "Send RECEIPT back\ninserted_count | skipped_count", font_size=12)

arrow(RIGHT_CX - 160, Y + 27, LEFT_CX + 170, Y + 27)
text(MID_CX - 30, Y + 10, "← receipt", font_size=11, color=GRAY)

rect(LEFT_CX - 170, Y, 340, 55, RED,
     "Receive RECEIPT\nLog counts for monitoring", font_size=12)

# ============================================================
# STEP 9: Prune confirmed rows
# ============================================================
Y += 80
rect(LEFT_CX - 170, Y, 340, 55, RED,
     "DELETE confirmed rows\nfrom local app7.db", font_size=13)
text(LEFT_CX + 180, Y + 10, "only prune rows", font_size=10, color=GRAY)
text(LEFT_CX + 180, Y + 24, "in the receipt", font_size=10, color=GRAY)

arrow(LEFT_CX, Y + 55, LEFT_CX, Y + 75)

# ============================================================
# STEP 10: Sleep and repeat
# ============================================================
Y += 80
rect(LEFT_CX - 140, Y, 280, 40, YELLOW,
     "Sleep 300s → repeat", font_size=13)

# Loop-back arrow (dashed, up the left side)
LOOP_X = 80
arrow(LEFT_CX - 140, Y + 20, LOOP_X, Y + 20, dashed=True)
arrow(LOOP_X, Y + 20, LOOP_X, 182, dashed=True)
arrow(LOOP_X, 182, LEFT_CX - 170, 182, dashed=True)
text(LOOP_X - 10, 600, "repeat", font_size=11, color=GRAY)

# ============================================================
# PROTOCOL SUMMARY (bottom right)
# ============================================================
SUM_Y = Y + 80
text(RIGHT_CX - 100, SUM_Y, "Protocol Summary", font_size=16)
text(RIGHT_CX - 100, SUM_Y + 25, "1. Worker → HEADER (16B fixed)", font_size=12, color=GRAY)
text(RIGHT_CX - 100, SUM_Y + 42, "2. Receiver → VERDICT (admission)", font_size=12, color=GRAY)
text(RIGHT_CX - 100, SUM_Y + 59, "3. Worker → PAYLOAD (variable)", font_size=12, color=GRAY)
text(RIGHT_CX - 100, SUM_Y + 76, "4. Receiver → RECEIPT (counts)", font_size=12, color=GRAY)
text(RIGHT_CX - 100, SUM_Y + 100, "Recommended: JSON+zlib (0x01)", font_size=12, color=GRAY)
text(RIGHT_CX - 100, SUM_Y + 117, "3-6× compression, debuggable", font_size=11, color=GRAY)

# ============================================================
# WRITE OUT
# ============================================================
doc = {
    "type": "excalidraw",
    "version": 2,
    "source": "http://localhost:3000",
    "elements": elements,
    "appState": {
        "gridSize": 20, "gridStep": 5,
        "gridModeEnabled": False, "viewBackgroundColor": "#ffffff",
    },
    "files": {},
}

out = sys.argv[1] if len(sys.argv) > 1 else "/dev/stdout"
with open(out, "w") as f:
    json.dump(doc, f, indent=2)
print(f"Generated {len(elements)} elements -> {out}", file=sys.stderr)
