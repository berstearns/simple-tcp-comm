#!/usr/bin/env python3
"""Generate collection pipeline diagram showing the 7-stage data flow.

Shows: App → Queue → Worker → Local DB → Collector → archive.db
with watermark tracking, deduplication layers, and table schema.
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

CX = 500  # main pipeline center

# ============================================================
# TITLE
# ============================================================
text(100, 10, "Collection Pipeline — 7 Stages", font_size=24)
text(100, 50, "App → Queue → Worker → Local DB → Collector → archive.db", font_size=16)
text(100, 76, "Watermark-based incremental · INSERT OR IGNORE dedup · 16 data tables", font_size=13)

# ============================================================
# 7-STAGE PIPELINE (main vertical flow)
# ============================================================
STAGE_W = 480
STAGE_X = CX - STAGE_W // 2

# Stage labels on the left
LABEL_X = 60

Y = 130
# Stage 1
text(LABEL_X, Y + 10, "Stage 1", font_size=14, color=FRAME)
rect(STAGE_X, Y, STAGE_W, 55, BLUE,
     "App logs to Room DB\n(Android emulator / device)", font_size=13)
text(STAGE_X + STAGE_W + 15, Y + 8, "Room persistence", font_size=10, color=GRAY)
text(STAGE_X + STAGE_W + 15, Y + 22, "SQLite on device", font_size=10, color=GRAY)

arrow(CX, Y + 55, CX, Y + 75)

# Stage 2
Y += 80
text(LABEL_X, Y + 10, "Stage 2", font_size=14, color=FRAME)
rect(STAGE_X, Y, STAGE_W, 55, BLUE,
     "UnifiedPayload serialized\n+ submitted to TCP queue", font_size=13)
text(STAGE_X + STAGE_W + 15, Y + 8, "JSON-RPC payload", font_size=10, color=GRAY)
text(STAGE_X + STAGE_W + 15, Y + 22, '{"method":"exec",...}', font_size=10, color=GRAY)

arrow(CX, Y + 55, CX, Y + 75)

# Stage 3
Y += 80
text(LABEL_X, Y + 10, "Stage 3", font_size=14, color=FRAME)
rect(STAGE_X, Y, STAGE_W, 55, YELLOW,
     "Job sits on Neptune queue server\nstatus: pending, in jobs.db", font_size=13)
text(STAGE_X + STAGE_W + 15, Y + 8, "Neptune :9999", font_size=10, color=GRAY)
text(STAGE_X + STAGE_W + 15, Y + 22, "fire-and-forget (202)", font_size=10, color=GRAY)

arrow(CX, Y + 55, CX, Y + 75)

# Stage 4
Y += 80
text(LABEL_X, Y + 10, "Stage 4", font_size=14, color=FRAME)
rect(STAGE_X, Y, STAGE_W, 55, RED,
     "Worker polls, accepts job\nevery 2 seconds (QUEUE_POLL)", font_size=13)
text(STAGE_X + STAGE_W + 15, Y + 8, "outbound TCP", font_size=10, color=GRAY)
text(STAGE_X + STAGE_W + 15, Y + 22, "behind NAT", font_size=10, color=GRAY)

arrow(CX, Y + 55, CX, Y + 75)

# Stage 5
Y += 80
text(LABEL_X, Y + 10, "Stage 5", font_size=14, color=FRAME)
rect(STAGE_X, Y, STAGE_W, 55, RED,
     "Worker executes handler\nsaves result to local app7.db", font_size=13)
text(STAGE_X + STAGE_W + 15, Y + 8, "INSERT OR IGNORE", font_size=10, color=GRAY)
text(STAGE_X + STAGE_W + 15, Y + 22, "idempotent", font_size=10, color=GRAY)

arrow(CX, Y + 55, CX, Y + 75)

# Stage 6
Y += 80
text(LABEL_X, Y + 10, "Stage 6", font_size=14, color=FRAME)
rect(STAGE_X, Y, STAGE_W, 55, GREEN,
     "Round-trip comparator verifies\npayload matches stored data", font_size=13)
text(STAGE_X + STAGE_W + 15, Y + 8, "verification pass", font_size=10, color=GRAY)
text(STAGE_X + STAGE_W + 15, Y + 22, "catches corruption", font_size=10, color=GRAY)

arrow(CX, Y + 55, CX, Y + 75)

# Stage 7
Y += 80
text(LABEL_X, Y + 10, "Stage 7", font_size=14, color=FRAME)
rect(STAGE_X, Y, STAGE_W, 55, LAVENDER,
     "Offline collector merges\nworker DBs → archive.db", font_size=13)
text(STAGE_X + STAGE_W + 15, Y + 8, "collector.py", font_size=10, color=GRAY)
text(STAGE_X + STAGE_W + 15, Y + 22, "--direct | --queue", font_size=10, color=GRAY)

arrow(CX, Y + 55, CX, Y + 75)

# Final: archive.db
Y += 80
rect(STAGE_X + 80, Y, 320, 50, PEACH, "archive.db", font_size=18)
text(STAGE_X + STAGE_W + 15, Y + 8, "16 tables + collection_log", font_size=10, color=GRAY)
text(STAGE_X + STAGE_W + 15, Y + 22, "_archive_id PK, _source_worker", font_size=10, color=GRAY)

# ============================================================
# COLLECTOR MODES (right side, detail)
# ============================================================
MODE_X = 870
MODE_Y = 130
text(MODE_X, MODE_Y, "Collector Modes", font_size=16)

Y = MODE_Y + 30
rect(MODE_X, Y, 320, 55, LAVENDER,
     "--direct\nread local worker DB files", font_size=12)
text(MODE_X + 10, Y + 58, "fast, requires file access", font_size=10, color=GRAY)

Y += 80
rect(MODE_X, Y, 320, 55, LAVENDER,
     "--queue\nsubmit query jobs via TCP", font_size=12)
text(MODE_X + 10, Y + 58, "works remotely, slower", font_size=10, color=GRAY)

# ============================================================
# DEDUPLICATION (right side)
# ============================================================
DEDUP_X = 870
DEDUP_Y = MODE_Y + 200
text(DEDUP_X, DEDUP_Y, "Deduplication (2 layers)", font_size=16)

Y = DEDUP_Y + 30
text(DEDUP_X, Y, "Layer 1: Watermarks (optimization)", font_size=13)
Y += 20
rect(DEDUP_X + 20, Y, 300, 55, YELLOW,
     "Track last_max_id per table\nSELECT WHERE id > watermark\nSkip already-collected rows", font_size=11)
text(DEDUP_X + 330, Y + 10, "stored in", font_size=10, color=GRAY)
text(DEDUP_X + 330, Y + 24, "collection_log", font_size=10, color=GRAY)

Y += 75
text(DEDUP_X, Y, "Layer 2: UNIQUE constraints (safety)", font_size=13)
Y += 20
rect(DEDUP_X + 20, Y, 300, 55, GREEN,
     "INSERT OR IGNORE\nUNIQUE(_source_worker,\n  device_id, local_id)", font_size=11)
text(DEDUP_X + 330, Y + 10, "catches edge cases", font_size=10, color=GRAY)
text(DEDUP_X + 330, Y + 24, "always safe", font_size=10, color=GRAY)

# ============================================================
# DATA TABLES (right side, below dedup)
# ============================================================
TAB_X = 870
TAB_Y = DEDUP_Y + 320
text(TAB_X, TAB_Y, "16 Data Tables", font_size=16)

categories = [
    ("Catalog (4)", PEACH, "comics, chapters, pages, images"),
    ("Events (6)", PEACH, "session_events, annotation_records,\nchat_messages, page_interactions,\napp_launch_records, settings_changes"),
    ("Sessions (4)", PEACH, "app, comic, chapter, page sessions"),
    ("Audit (1)", PEACH, "ingest_batches (source of truth)"),
]

Y = TAB_Y + 25
for cat_name, color, desc in categories:
    rect(TAB_X, Y, 180, 35, color, cat_name, font_size=12)
    text(TAB_X + 190, Y + 8, desc, font_size=10, color=GRAY)
    Y += 55

# ============================================================
# ARCHIVE SCHEMA DETAIL
# ============================================================
SCHEMA_Y = TAB_Y + 250
text(TAB_X, SCHEMA_Y, "Archive Schema", font_size=16)

Y = SCHEMA_Y + 25
schema_items = [
    "_archive_id INTEGER PRIMARY KEY",
    "_source_worker TEXT NOT NULL",
    "UNIQUE(_source_worker, device_id, local_id)",
    "collection_log tracks watermarks",
    "FK constraints dropped (read-only)",
]
for item in schema_items:
    text(TAB_X + 10, Y, f"• {item}", font_size=11, color=GRAY)
    Y += 18

# ============================================================
# COLLECTOR COMMANDS (bottom)
# ============================================================
CMD_Y = TAB_Y + 370
text(TAB_X, CMD_Y, "Collector Commands", font_size=14)
cmds = [
    "collector.py collect --direct /path/to/worker.db",
    "collector.py collect --queue --worker-name NAME",
    "collector.py status",
    "collector.py verify --direct /path/to/worker.db",
    "collector.py prune --days 90",
]
Y = CMD_Y + 22
for cmd in cmds:
    rect(TAB_X, Y, 450, 25, YELLOW, cmd, font_size=10)
    Y += 30

# ============================================================
# LEGEND
# ============================================================
LEG_X = 870
LEG_Y = CMD_Y + 200
text(LEG_X, LEG_Y, "Legend", font_size=16)
legend = [
    (BLUE, "App / Client / Input"),
    (YELLOW, "Queue / Control / Optimization"),
    (RED, "Worker Processing"),
    (GREEN, "Verification / Safety"),
    (LAVENDER, "Collector / Aggregation"),
    (PEACH, "Database / Schema"),
]
for i, (c, name) in enumerate(legend):
    yy = LEG_Y + 25 + i * 35
    rect(LEG_X, yy, 24, 24, c, label=None)
    text(LEG_X + 34, yy + 5, name, font_size=12)

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
