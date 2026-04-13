#!/usr/bin/env python3
"""Generate detailed job queue flow diagram for TCP :9999 path.

Shows: Client → Queue Server → Worker poll → Handler dispatch → Result return.
Vertical flow, step-by-step protocol detail.
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

CX = 500  # main flow center

# ============================================================
# TITLE
# ============================================================
text(100, 10, "Job Queue Flow — TCP :9999 JSON-RPC", font_size=24)
text(100, 50, "Client → Queue Server → Worker poll → Handler → Result", font_size=16)
text(100, 76, "Fire-and-forget enqueue · 202 immediate · Worker polls every 2s", font_size=13)

# ============================================================
# STEP 1: Client submits job
# ============================================================
Y = 130
text(100, Y, "① Client Submits Job", font_size=16, color=GRAY)
Y += 30
rect(CX - 200, Y, 400, 55, BLUE,
     "Client / Android App\nTCP connect → send JSON payload", font_size=13)
text(CX + 210, Y + 8, '{"method": "exec",', font_size=11, color=GRAY)
text(CX + 210, Y + 22, ' "params": {"db": "app7",', font_size=11, color=GRAY)
text(CX + 210, Y + 36, '   "sql": "INSERT ..."}}', font_size=11, color=GRAY)

arrow(CX, Y + 55, CX, Y + 80)
text(CX + 10, Y + 60, "TCP :9999", font_size=11, color=GRAY)

# ============================================================
# STEP 2: Queue Server receives and enqueues
# ============================================================
Y += 90
text(100, Y, "② Queue Server Enqueues", font_size=16, color=GRAY)
Y += 30
rect(CX - 200, Y, 400, 50, YELLOW,
     "Queue Server: parse JSON-RPC\nvalidate method, assign job_id", font_size=13)

arrow(CX, Y + 50, CX, Y + 75)

Y += 80
rect(CX - 150, Y, 300, 45, PEACH,
     "INSERT INTO jobs\n(status='pending', payload=...)", font_size=12)
text(CX + 160, Y + 10, "jobs.db (SQLite)", font_size=11, color=GRAY)

arrow(CX, Y + 45, CX, Y + 65)

Y += 70
rect(CX - 120, Y, 240, 40, YELLOW, "Return 202 + job_id", font_size=13)
text(CX + 130, Y + 12, "fire-and-forget", font_size=11, color=GRAY)

# ============================================================
# STEP 3: Worker polls
# ============================================================
Y += 80
text(100, Y, "③ Worker Polls for Jobs", font_size=16, color=GRAY)
Y += 30
rect(CX - 200, Y, 400, 50, RED,
     "Worker: GET /poll?worker=NAME\nevery QUEUE_POLL (2 seconds)", font_size=13)
text(CX + 210, Y + 10, "outbound TCP only", font_size=11, color=GRAY)
text(CX + 210, Y + 24, "(NAT-friendly)", font_size=11, color=GRAY)

arrow(CX, Y + 50, CX, Y + 75)

Y += 80
rect(CX - 150, Y, 300, 45, YELLOW,
     "UPDATE jobs SET status='running'\nWHERE worker=NAME", font_size=12)

arrow(CX, Y + 45, CX, Y + 65)

# ============================================================
# STEP 4: Handler dispatch
# ============================================================
Y += 70
text(100, Y, "④ Handler Dispatch", font_size=16, color=GRAY)
Y += 30
rect(CX - 120, Y, 240, 40, YELLOW, "Dispatch by method", font_size=14)

# Three handler branches
HANDLER_Y = Y + 65
H_W = 220
H_GAP = 30
H_START = CX - (3 * H_W + 2 * H_GAP) // 2

# Branch arrows
arrow(CX - 40, Y + 40, H_START + H_W // 2, HANDLER_Y)
arrow(CX, Y + 40, H_START + H_W + H_GAP + H_W // 2, HANDLER_Y)
arrow(CX + 40, Y + 40, H_START + 2 * (H_W + H_GAP) + H_W // 2, HANDLER_Y)

rect(H_START, HANDLER_Y, H_W, 55, RED,
     "query\nSQL against local DB", font_size=12)
text(H_START + 10, HANDLER_Y + 58, "SELECT/INSERT on app7.db", font_size=10, color=GRAY)

rect(H_START + H_W + H_GAP, HANDLER_Y, H_W, 55, RED,
     "exec\nshell command", font_size=12)
text(H_START + H_W + H_GAP + 10, HANDLER_Y + 58, "subprocess.run()", font_size=10, color=GRAY)

rect(H_START + 2 * (H_W + H_GAP), HANDLER_Y, H_W, 55, RED,
     "ping\nhealth check", font_size=12)
text(H_START + 2 * (H_W + H_GAP) + 10, HANDLER_Y + 58, "return alive + stats", font_size=10, color=GRAY)

# Local DB
DB_Y = HANDLER_Y + 90
rect(H_START + 30, DB_Y, 160, 40, PEACH, "app7.db (local)", font_size=12)
arrow(H_START + H_W // 2, HANDLER_Y + 55, H_START + 110, DB_Y)

# ============================================================
# STEP 5: Result return
# ============================================================
Y = DB_Y + 70
text(100, Y, "⑤ Result Return", font_size=16, color=GRAY)
Y += 30

# Converge arrows from handlers
arrow(H_START + H_W // 2, HANDLER_Y + 55, CX, Y)
arrow(H_START + H_W + H_GAP + H_W // 2, HANDLER_Y + 55, CX, Y)
arrow(H_START + 2 * (H_W + H_GAP) + H_W // 2, HANDLER_Y + 55, CX, Y)

rect(CX - 200, Y, 400, 50, RED,
     "Worker sends result back\nPOST /result {job_id, status, output}", font_size=13)

arrow(CX, Y + 50, CX, Y + 75)

Y += 80
rect(CX - 150, Y, 300, 45, YELLOW,
     "UPDATE jobs SET status='done'\nresult = output", font_size=12)

arrow(CX, Y + 45, CX, Y + 65)

# ============================================================
# STEP 6: Client retrieves
# ============================================================
Y += 70
text(100, Y, "⑥ Client Retrieves Result", font_size=16, color=GRAY)
Y += 30
rect(CX - 180, Y, 360, 50, BLUE,
     "Client polls GET /result?job_id=...\nor uses wait_for_result()", font_size=13)
text(CX + 190, Y + 10, "polling or callback", font_size=11, color=GRAY)
text(CX + 190, Y + 25, "based on job_id", font_size=11, color=GRAY)

# ============================================================
# JOB LIFECYCLE (right side)
# ============================================================
LC_X = 900
LC_Y = 160
text(LC_X, LC_Y, "Job Lifecycle", font_size=16)

states = [
    ("pending", YELLOW, "job created, waiting"),
    ("running", RED, "worker accepted"),
    ("done", GREEN, "result available"),
    ("failed", "#ffc9c9", "handler error"),
]
for i, (state, color, desc) in enumerate(states):
    sy = LC_Y + 30 + i * 60
    rect(LC_X, sy, 160, 40, color, state, font_size=14)
    text(LC_X + 170, sy + 12, desc, font_size=11, color=GRAY)
    if i < len(states) - 1 and i < 2:
        arrow(LC_X + 80, sy + 40, LC_X + 80, sy + 60)

# failed branch from running
arrow(LC_X + 160, LC_Y + 30 + 1 * 60 + 20, LC_X + 200, LC_Y + 30 + 3 * 60 + 20)

# ============================================================
# LEGEND
# ============================================================
LEG_X = 900
LEG_Y = 480
text(LEG_X, LEG_Y, "Legend", font_size=16)
legend = [
    (BLUE, "Client / External"),
    (YELLOW, "Queue Server / Dispatch"),
    (RED, "Worker / Handler"),
    (PEACH, "Database (SQLite)"),
    (GREEN, "Success / Merge"),
]
for i, (c, name) in enumerate(legend):
    yy = LEG_Y + 30 + i * 38
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
