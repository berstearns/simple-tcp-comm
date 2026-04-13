#!/usr/bin/env python3
"""Generate system architecture overview diagram for simple-tcp-comm.

Vertical flow: clients at top, archive at bottom.
Shows both TCP paths: queue (:9999) and archive drain (:8080).
Shows NAT boundary, all worker nodes, collector, and final archive.
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

# ============================================================
# Palette
# ============================================================
BLUE     = "#a5d8ff"   # clients, entry points, external
YELLOW   = "#ffec99"   # queue operations, polling, dispatch
PEACH    = "#ffd8a8"   # databases (SQLite)
RED      = "#ffc9c9"   # worker processing, handlers
GREEN    = "#b2f2bb"   # archive receiver, data aggregation
LAVENDER = "#e8deee"   # collector, protocol
GRAY     = "#495057"
FRAME    = "#868e96"

CX = 650  # main column center

# ============================================================
# TITLE
# ============================================================
text(150, 10, "simple-tcp-comm — System Architecture", font_size=24)
text(150, 50, "TCP JSON-RPC :9999 · Binary Archive Drain :8080 · SQLite · NAT-friendly", font_size=16)
text(150, 76, "Queue-Worker-Collector · Fire-and-forget · Idempotent handlers · Watermark collection", font_size=13)

# ============================================================
# CLIENT
# ============================================================
CLIENT_Y = 130
rect(CX - 150, CLIENT_Y, 300, 50, BLUE, "Android App / Client", font_size=16)
text(CX + 160, CLIENT_Y + 18, "submits UnifiedPayload via TCP", font_size=11, color=GRAY)

# Arrow: Client → Neptune
arrow(CX, CLIENT_Y + 50, CX, CLIENT_Y + 85)
text(CX + 10, CLIENT_Y + 58, "TCP :9999", font_size=11, color=GRAY)

# ============================================================
# NEPTUNE FRAME
# ============================================================
NEPT_Y = 220
NEPT_H = 230
# Dashed frame
rect(130, NEPT_Y, 1100, NEPT_H, "transparent", label=None, rounded=False)
elements[-1]["strokeStyle"] = "dashed"
elements[-1]["strokeColor"] = FRAME
text(140, NEPT_Y + 8, "Neptune (Digital Ocean VPS)", font_size=14, color=FRAME)

# Queue Server (left)
QS_X = 170
QS_Y = NEPT_Y + 50
QS_W = 430
QS_H = 55
rect(QS_X, QS_Y, QS_W, QS_H, YELLOW,
     "Queue Server (server.py)\nTCP :9999 · JSON-RPC · SQLite-backed", font_size=13)
QS_CX = QS_X + QS_W // 2  # 385

# Archive Receiver (right)
AR_X = 700
AR_Y = NEPT_Y + 50
AR_W = 480
AR_H = 55
rect(AR_X, AR_Y, AR_W, AR_H, GREEN,
     "Archive Receiver (archive_receiver.py)\nTCP :8080 · Binary protocol · Admission control", font_size=13)
AR_CX = AR_X + AR_W // 2  # 940

# Databases under Queue Server
DB_Y = QS_Y + 70
rect(QS_X + 20, DB_Y, 170, 35, PEACH, "jobs table", font_size=12)
rect(QS_X + 210, DB_Y, 170, 35, PEACH, "workers table", font_size=12)
text(QS_X + 20, DB_Y + 40, "pending → running → done", font_size=10, color=GRAY)

# Annotation under Archive Receiver
text(AR_X + 10, AR_Y + 60, "HEADER → VERDICT → PAYLOAD → RECEIPT", font_size=10, color=GRAY)
text(AR_X + 10, AR_Y + 75, "JSON / JSON+zlib / struct-pack", font_size=10, color=GRAY)

# Arrow: Client → Queue Server
arrow(CX, CLIENT_Y + 85, QS_CX, QS_Y)

# ============================================================
# NAT BOUNDARY
# ============================================================
NAT_Y = NEPT_Y + NEPT_H + 20  # 470
# Dashed horizontal line
arrow(80, NAT_Y, 1280, NAT_Y, dashed=True)
elements[-1]["endArrowhead"] = None  # just a line, no arrowhead
text(CX - 60, NAT_Y - 18, "═══  NAT Boundary  ═══", font_size=13, color=FRAME)
text(CX - 100, NAT_Y + 5, "Workers behind NAT — outbound connections only", font_size=11, color=GRAY)

# ============================================================
# WORKERS
# ============================================================
W_Y = NAT_Y + 50  # 520
W_W = 320
W_H = 210
W_GAP = 40

# Worker 1
W1_X = 80
rect(W1_X, W_Y, W_W, W_H, "transparent", label=None, rounded=False)
elements[-1]["strokeStyle"] = "dashed"
elements[-1]["strokeColor"] = FRAME
text(W1_X + 10, W_Y + 8, "Worker 1 (homelab)", font_size=12, color=FRAME)

rect(W1_X + 30, W_Y + 40, 260, 40, RED, "worker.py (poll loop)", font_size=12)
rect(W1_X + 30, W_Y + 95, 260, 40, RED, "drain.py (push loop)", font_size=12)
rect(W1_X + 80, W_Y + 155, 160, 35, PEACH, "app7.db", font_size=12)
text(W1_X + 30, W_Y + 140, "local SQLite", font_size=10, color=GRAY)

W1_CX = W1_X + W_W // 2  # 240

# Worker 2
W2_X = W1_X + W_W + W_GAP  # 440
rect(W2_X, W_Y, W_W, W_H, "transparent", label=None, rounded=False)
elements[-1]["strokeStyle"] = "dashed"
elements[-1]["strokeColor"] = FRAME
text(W2_X + 10, W_Y + 8, "Worker 2", font_size=12, color=FRAME)

rect(W2_X + 30, W_Y + 40, 260, 40, RED, "worker.py (poll loop)", font_size=12)
rect(W2_X + 30, W_Y + 95, 260, 40, RED, "drain.py (push loop)", font_size=12)
rect(W2_X + 80, W_Y + 155, 160, 35, PEACH, "app7.db", font_size=12)

W2_CX = W2_X + W_W // 2  # 600

# Worker N
WN_X = W2_X + W_W + W_GAP  # 800
rect(WN_X, W_Y, W_W, W_H, "transparent", label=None, rounded=False)
elements[-1]["strokeStyle"] = "dashed"
elements[-1]["strokeColor"] = FRAME
text(WN_X + 10, W_Y + 8, "Worker N", font_size=12, color=FRAME)

rect(WN_X + 30, W_Y + 40, 260, 40, RED, "worker.py (poll loop)", font_size=12)
rect(WN_X + 30, W_Y + 95, 260, 40, RED, "drain.py (push loop)", font_size=12)
rect(WN_X + 80, W_Y + 155, 160, 35, PEACH, "app7.db", font_size=12)

WN_CX = WN_X + W_W // 2  # 960

# "..." between workers
text(W2_X + W_W + 8, W_Y + 90, "· · ·", font_size=16, color=GRAY)

# ============================================================
# ARROWS: Queue Server → Workers (poll path, left side)
# ============================================================
# Trunk from Queue Server down through NAT
POLL_LANE_X = QS_CX - 50  # 335
arrow(QS_CX, QS_Y + QS_H, QS_CX, NAT_Y - 5)
# Below NAT, fan out to each worker's worker.py
arrow(QS_CX, NAT_Y + 5, W1_CX, W_Y + 40)
arrow(QS_CX, NAT_Y + 5, W2_CX, W_Y + 40)
arrow(QS_CX, NAT_Y + 5, WN_CX, W_Y + 40)

# Labels on poll arrows
text(QS_CX + 10, QS_Y + QS_H + 15, "poll every 2s", font_size=11, color=GRAY)
text(QS_CX + 10, QS_Y + QS_H + 30, "worker → server", font_size=10, color=GRAY)

# ============================================================
# ARROWS: Workers → Archive Receiver (drain path, right side)
# ============================================================
# Each worker's drain.py sends up to Archive Receiver
DRAIN_LANE_Y = NAT_Y - 30
# Worker 1 drain → up
arrow(W1_CX + 80, W_Y + 95, W1_CX + 80, DRAIN_LANE_Y)
arrow(W1_CX + 80, DRAIN_LANE_Y, AR_CX, AR_Y + AR_H)
# Worker 2 drain → up
arrow(W2_CX + 80, W_Y + 95, AR_CX, AR_Y + AR_H)
# Worker N drain → up
arrow(WN_CX + 80, W_Y + 95, WN_CX + 80, DRAIN_LANE_Y)
arrow(WN_CX + 80, DRAIN_LANE_Y, AR_CX, AR_Y + AR_H)

# Labels on drain arrows
text(AR_CX + 20, AR_Y + AR_H + 10, "drain every 300s", font_size=11, color=GRAY)
text(AR_CX + 20, AR_Y + AR_H + 25, "cold rows (>1hr old)", font_size=10, color=GRAY)

# ============================================================
# COLLECTOR
# ============================================================
COLL_Y = W_Y + W_H + 60  # 790
rect(CX - 170, COLL_Y, 340, 55, LAVENDER,
     "Collector (collector.py)\n--direct | --queue", font_size=14)
text(CX + 180, COLL_Y + 10, "incremental watermarks", font_size=11, color=GRAY)
text(CX + 180, COLL_Y + 25, "INSERT OR IGNORE dedup", font_size=11, color=GRAY)

# Arrows: Workers → Collector (converging)
arrow(W1_CX, W_Y + W_H, CX - 80, COLL_Y)
arrow(W2_CX, W_Y + W_H, CX, COLL_Y)
arrow(WN_CX, W_Y + W_H, CX + 80, COLL_Y)
text(W2_CX + 30, W_Y + W_H + 10, "direct read / queue query", font_size=11, color=GRAY)

# ============================================================
# ARCHIVE DB
# ============================================================
ARCH_Y = COLL_Y + 80
rect(CX - 140, ARCH_Y, 280, 50, PEACH, "archive.db", font_size=16)
arrow(CX, COLL_Y + 55, CX, ARCH_Y)

# Annotations
text(CX + 150, ARCH_Y + 8, "16 data tables", font_size=11, color=GRAY)
text(CX + 150, ARCH_Y + 22, "_source_worker column", font_size=11, color=GRAY)
text(CX + 150, ARCH_Y + 36, "collection_log watermarks", font_size=11, color=GRAY)

# ============================================================
# DATA TABLE CATEGORIES (below archive.db)
# ============================================================
CAT_Y = ARCH_Y + 70
rect(CX - 360, CAT_Y, 200, 40, PEACH, "Catalog (4)", font_size=12)
text(CX - 355, CAT_Y + 42, "comics, chapters,\npages, images", font_size=10, color=GRAY)

rect(CX - 130, CAT_Y, 200, 40, PEACH, "Events (6)", font_size=12)
text(CX - 125, CAT_Y + 42, "session_events,\nannotation_records, ...", font_size=10, color=GRAY)

rect(CX + 100, CAT_Y, 200, 40, PEACH, "Sessions (4)", font_size=12)
text(CX + 105, CAT_Y + 42, "app, comic, chapter,\npage sessions", font_size=10, color=GRAY)

rect(CX + 330, CAT_Y, 200, 40, PEACH, "Audit (1)", font_size=12)
text(CX + 335, CAT_Y + 42, "ingest_batches\n(source of truth)", font_size=10, color=GRAY)

# Arrows from archive.db to categories
arrow(CX - 60, ARCH_Y + 50, CX - 260, CAT_Y)
arrow(CX - 20, ARCH_Y + 50, CX - 30, CAT_Y)
arrow(CX + 20, ARCH_Y + 50, CX + 200, CAT_Y)
arrow(CX + 60, ARCH_Y + 50, CX + 430, CAT_Y)

# ============================================================
# LEGEND
# ============================================================
LEG_X = 1300
LEG_Y = 130
text(LEG_X, LEG_Y, "Legend", font_size=16)
legend = [
    (BLUE, "Clients / Entry Points"),
    (YELLOW, "Queue Operations"),
    (GREEN, "Archive Receiver / Aggregation"),
    (RED, "Worker Processing"),
    (PEACH, "Databases (SQLite)"),
    (LAVENDER, "Collector / Protocol"),
]
for i, (c, name) in enumerate(legend):
    yy = LEG_Y + 30 + i * 42
    rect(LEG_X, yy, 28, 28, c, label=None)
    text(LEG_X + 38, yy + 7, name, font_size=12)

text(LEG_X, LEG_Y + 30 + 6 * 42 + 10, "Dashed boxes = server/worker", font_size=11, color=GRAY)
text(LEG_X, LEG_Y + 30 + 6 * 42 + 28, "boundaries", font_size=11, color=GRAY)
text(LEG_X, LEG_Y + 30 + 6 * 42 + 50, "Two TCP paths:", font_size=11, color=GRAY)
text(LEG_X, LEG_Y + 30 + 6 * 42 + 66, "  :9999 = job queue", font_size=11, color=GRAY)
text(LEG_X, LEG_Y + 30 + 6 * 42 + 82, "  :8080 = archive drain", font_size=11, color=GRAY)

# ============================================================
# KEY DESIGN PROPERTIES (bottom-right)
# ============================================================
PROP_Y = LEG_Y + 400
text(LEG_X, PROP_Y, "Design Properties", font_size=14)
props = [
    "Workers behind NAT (outbound only)",
    "Fire-and-forget enqueue (202)",
    "Idempotent handlers (INSERT OR IGNORE)",
    "Watermark-based incremental collection",
    "Audit via ingest_batches (source of truth)",
    "Poll interval: 2s (queue), 300s (drain)",
]
for i, p in enumerate(props):
    text(LEG_X, PROP_Y + 22 + i * 18, f"• {p}", font_size=11, color=GRAY)

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
