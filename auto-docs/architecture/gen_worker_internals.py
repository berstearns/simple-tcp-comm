#!/usr/bin/env python3
"""Generate worker node internals diagram.

Shows: poll loop, handler dispatch, local DB layout, drain cycle,
environment variables, and tmux deployment.
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

# ============================================================
# TITLE
# ============================================================
text(100, 10, "Worker Node Internals", font_size=24)
text(100, 50, "Poll loop (worker.py) + Drain loop (drain.py) + Local databases", font_size=16)
text(100, 76, "Behind NAT · Outbound TCP only · Idempotent handlers · tmux deployment", font_size=13)

# ============================================================
# ENVIRONMENT VARIABLES (top left)
# ============================================================
ENV_X = 100
ENV_Y = 120
text(ENV_X, ENV_Y, "Environment Variables", font_size=14, color=FRAME)
envs = [
    "QUEUE_HOST = neptune.example.com",
    "QUEUE_PORT = 9999",
    "QUEUE_POLL = 2   (seconds)",
    "QUEUE_DBS  = /path/to/app7.db",
    "WORKER_NAME = homelab-01",
]
for i, e in enumerate(envs):
    rect(ENV_X, ENV_Y + 24 + i * 32, 320, 28, YELLOW, e, font_size=11)

# ============================================================
# WORKER NODE FRAME
# ============================================================
NODE_X = 80
NODE_Y = 310
NODE_W = 1200
NODE_H = 820
rect(NODE_X, NODE_Y, NODE_W, NODE_H, "transparent", label=None, rounded=False)
elements[-1]["strokeStyle"] = "dashed"
elements[-1]["strokeColor"] = FRAME
text(NODE_X + 10, NODE_Y + 8, "Worker Node (single machine, behind NAT)", font_size=14, color=FRAME)

# ============================================================
# POLL LOOP (left side of node)
# ============================================================
POLL_X = 140
POLL_Y = NODE_Y + 50

text(POLL_X, POLL_Y, "Poll Loop (worker.py)", font_size=16)

Y = POLL_Y + 30
rect(POLL_X, Y, 280, 40, RED, "sleep(QUEUE_POLL)", font_size=13)
text(POLL_X + 290, Y + 12, "2 seconds", font_size=11, color=GRAY)

Y += 60
rect(POLL_X, Y, 280, 45, BLUE,
     "GET /poll?worker=NAME\n→ Neptune :9999", font_size=12)
text(POLL_X + 290, Y + 10, "outbound TCP", font_size=11, color=GRAY)

Y += 65
rect(POLL_X + 40, Y, 200, 35, YELLOW, "job received?", font_size=13)

# No job → loop back
arrow(POLL_X + 240, Y + 17, POLL_X + 330, Y + 17)
text(POLL_X + 340, Y + 8, "no → sleep", font_size=11, color=GRAY)
arrow(POLL_X + 330, Y + 17, POLL_X + 330, POLL_Y + 50)
arrow(POLL_X + 330, POLL_Y + 50, POLL_X + 280, POLL_Y + 50)

# Yes → dispatch
arrow(POLL_X + 140, Y + 35, POLL_X + 140, Y + 55)
text(POLL_X + 150, Y + 38, "yes", font_size=11, color=GRAY)

Y += 60
rect(POLL_X - 10, Y, 300, 40, YELLOW,
     "Dispatch by method field", font_size=13)

# Handler branches
H_Y = Y + 60
H_W = 200

rect(POLL_X - 30, H_Y, H_W, 55, RED,
     "query handler\nSQL on local DB", font_size=12)
arrow(POLL_X + 50, Y + 40, POLL_X + 70, H_Y)

rect(POLL_X - 30 + H_W + 20, H_Y, H_W, 55, RED,
     "exec handler\nshell subprocess", font_size=12)
arrow(POLL_X + 140, Y + 40, POLL_X + 190, H_Y)

# Third handler to the right
rect(POLL_X - 30 + 2 * (H_W + 20), H_Y, H_W, 55, RED,
     "ping handler\nhealth check", font_size=12)
arrow(POLL_X + 230, Y + 40, POLL_X + 310 + 80, H_Y)

# Result arrow
RES_Y = H_Y + 80
rect(POLL_X + 20, RES_Y, 250, 45, BLUE,
     "POST /result to Neptune\n{job_id, status, output}", font_size=12)
arrow(POLL_X + 70, H_Y + 55, POLL_X + 145, RES_Y)
arrow(POLL_X + 190, H_Y + 55, POLL_X + 145, RES_Y)
arrow(POLL_X + 310 + 80, H_Y + 55, POLL_X + 145, RES_Y)

# Loop back to sleep
arrow(POLL_X + 145, RES_Y + 45, POLL_X + 145, RES_Y + 65)
rect(POLL_X + 45, RES_Y + 65, 200, 35, YELLOW, "→ sleep → repeat", font_size=12)

# ============================================================
# LOCAL DATABASES (center of node)
# ============================================================
DB_X = 720
DB_Y = NODE_Y + 50
text(DB_X, DB_Y, "Local Databases", font_size=16)

Y = DB_Y + 30
rect(DB_X, Y, 220, 50, PEACH,
     "app7.db\n(main application data)", font_size=12)
text(DB_X + 230, Y + 10, "16 data tables", font_size=10, color=GRAY)
text(DB_X + 230, Y + 24, "FK hierarchy", font_size=10, color=GRAY)

Y += 65
rect(DB_X, Y, 220, 50, PEACH,
     "main.db\n(configuration, state)", font_size=12)

Y += 65
rect(DB_X, Y, 220, 50, PEACH,
     "logs.db\n(operational logs)", font_size=12)

# Arrow from query handler to DB
arrow(POLL_X + 170, H_Y + 27, DB_X, DB_Y + 55)
text(POLL_X + 300, H_Y - 10, "read/write", font_size=10, color=GRAY)

# ============================================================
# DRAIN LOOP (bottom of node)
# ============================================================
DRAIN_X = 140
DRAIN_Y = NODE_Y + 480

text(DRAIN_X, DRAIN_Y, "Drain Loop (drain.py)", font_size=16)

Y = DRAIN_Y + 30
rect(DRAIN_X, Y, 280, 40, RED, "sleep(300s)", font_size=13)
text(DRAIN_X + 290, Y + 12, "5 minutes", font_size=11, color=GRAY)

Y += 55
rect(DRAIN_X, Y, 280, 50, PEACH,
     "Scan for cold rows\nWHERE age > 1 hour", font_size=12)

# Arrow from DB to drain
arrow(DB_X, DB_Y + 130, DRAIN_X + 280, DRAIN_Y + 90)
text(DB_X - 120, DB_Y + 200, "read cold rows", font_size=10, color=GRAY)

Y += 65
rect(DRAIN_X, Y, 280, 45, RED,
     "Batch by table_id\nApply batch_size limit", font_size=12)

Y += 60
rect(DRAIN_X, Y, 280, 50, BLUE,
     "TCP → Neptune :8080\nSend HEADER + PAYLOAD", font_size=12)
text(DRAIN_X + 290, Y + 10, "binary protocol", font_size=11, color=GRAY)
text(DRAIN_X + 290, Y + 24, "HEADER → VERDICT →", font_size=10, color=GRAY)
text(DRAIN_X + 290, Y + 38, "PAYLOAD → RECEIPT", font_size=10, color=GRAY)

Y += 65
rect(DRAIN_X, Y, 280, 45, GREEN,
     "Receive RECEIPT\ninserted / skipped counts", font_size=12)

Y += 60
rect(DRAIN_X, Y, 280, 45, RED,
     "DELETE confirmed rows\nfrom local DB", font_size=12)
text(DRAIN_X + 290, Y + 12, "prune only receipted", font_size=10, color=GRAY)

Y += 60
rect(DRAIN_X + 30, Y, 220, 35, YELLOW, "→ sleep → repeat", font_size=12)

# ============================================================
# TMUX DEPLOYMENT (right side)
# ============================================================
TMUX_X = 720
TMUX_Y = NODE_Y + 480
text(TMUX_X, TMUX_Y, "tmux Deployment", font_size=16)

Y = TMUX_Y + 30
rect(TMUX_X, Y, 450, 30, BLUE, "Session: stcp-w", font_size=12)

Y += 40
rect(TMUX_X + 20, Y, 200, 30, RED, "window: worker", font_size=11)
rect(TMUX_X + 230, Y, 200, 30, RED, "window: drain", font_size=11)

Y += 40
rect(TMUX_X + 20, Y, 200, 40, RED,
     "pane: job-worker\npython3 worker.py", font_size=10)
rect(TMUX_X + 230, Y, 200, 40, RED,
     "pane: drain-push\npython3 drain.py", font_size=10)

# Neptune tmux (for reference)
Y += 65
text(TMUX_X, Y, "Neptune tmux (for reference)", font_size=12, color=GRAY)
Y += 20
rect(TMUX_X, Y, 450, 30, GREEN, "Session: stcp", font_size=12)
Y += 35
rect(TMUX_X + 20, Y, 200, 40, YELLOW,
     "window: queue\nserver.py :9999", font_size=10)
rect(TMUX_X + 230, Y, 200, 40, GREEN,
     "window: archive\nreceiver.py :8080", font_size=10)

# ============================================================
# EXTERNAL CONNECTIONS (arrows going out of node frame)
# ============================================================
# Arrow from node to Neptune (queue)
arrow(POLL_X + 140, NODE_Y, POLL_X + 140, NODE_Y - 30)
text(POLL_X + 150, NODE_Y - 40, "→ Neptune :9999 (poll + result)", font_size=11, color=BLUE)

# Arrow from node to Neptune (drain)
arrow(DRAIN_X + 140, NODE_Y, DRAIN_X + 140, NODE_Y - 50)
text(DRAIN_X + 290, NODE_Y - 50, "→ Neptune :8080 (drain)", font_size=11, color=GREEN)

# ============================================================
# LEGEND
# ============================================================
LEG_X = 1000
LEG_Y = 130
text(LEG_X, LEG_Y, "Legend", font_size=16)
legend = [
    (BLUE, "Network / TCP"),
    (YELLOW, "Control flow / Queue"),
    (RED, "Processing / Handlers"),
    (PEACH, "Databases (SQLite)"),
    (GREEN, "Archive / Receipt"),
    (LAVENDER, "Protocol / Serialization"),
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
