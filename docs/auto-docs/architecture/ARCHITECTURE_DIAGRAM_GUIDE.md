# Architecture Diagram Generator — Recipe

Reusable pattern for producing Excalidraw diagrams of the
simple-tcp-comm queue-worker-collector architecture. Follow top-to-bottom;
adapt component templates from §6 as needed for new views of the system.

Modeled after the LLM Architecture Diagram Generator at
`/home/b/excalidraw-math-sync/drawings/LLM_DIAGRAM_GUIDE.md`.

## Reference implementations

All diagrams live in `diagrams-instances/`. Generator scripts live in
this directory. When creating a new diagram, **start from whichever
reference below shares the most structural similarity with the target**.

| File | Focus | Elements | Start here when… |
|------|-------|----------|------------------|
| `system-overview.excalidraw` | Full topology: client → Neptune → workers → collector → archive | ~120 | you need the big picture, all components, both TCP paths |
| `job-queue-flow.excalidraw` | TCP :9999 path step-by-step: enqueue → poll → dispatch → result | ~90 | you need job lifecycle detail, handler dispatch, result flow |
| `archive-drain-flow.excalidraw` | TCP :8080 binary protocol: HEADER → VERDICT → PAYLOAD → RECEIPT | ~80 | you need protocol detail, serialization formats, admission control |
| `worker-internals.excalidraw` | Inside a worker node: poll loop, drain loop, local DBs, tmux deploy | ~120 | you need worker architecture, handler internals, deployment layout |
| `collection-pipeline.excalidraw` | 7-stage pipeline: app → queue → worker → collector → archive.db | ~110 | you need data lineage, watermarks, dedup layers, table schema |

**Selection heuristic**: pick the reference that matches the structural
pattern you need. If you need a new detail view (e.g., a specific handler,
a specific table flow), copy the closest generator and modify.

---

## 1. Canvas convention

- **Orientation**: vertical flow, *input at top*, *output at bottom*.
  Excalidraw Y grows downward. This matches data flow direction
  (client → server → worker → archive).
- **Bounds**: typical X ∈ [60, 1500], Y ∈ [10, 1100] for standard
  diagrams. Extend as needed — canvas is unlimited.
- **Main column center**: `CX = 500–700` depending on diagram width.
  System overview uses CX=650 (wider), detail flows use CX=500.
- **Annotation column**: right of main flow, X ≈ CX + 200+.
- **Legend**: right gutter, X ≈ 1250+.
- **Row pitch**: minimum 70 px between rows. 80 px standard. 100+ px
  for spacious layouts.
- **Column pitch**: minimum 40 px gap between side-by-side components.
  Worker frames use 40 px gap, handler branches use 20-30 px.

## 2. Color palette (semantic — keep consistent across all diagrams)

| Hex | Role |
|-----|------|
| `#a5d8ff` | **BLUE** — clients, external entry points, TCP connections |
| `#ffec99` | **YELLOW** — queue operations, control flow, dispatch, polling |
| `#b2f2bb` | **GREEN** — archive receiver, data aggregation, verification |
| `#ffc9c9` | **RED** — worker processing, handlers, execution |
| `#ffd8a8` | **PEACH** — databases (all SQLite instances) |
| `#e8deee` | **LAVENDER** — collector, protocol layers, serialization |

Annotation gray `#495057` for dimension labels and notes.
Dashed frame gray `#868e96` for component boundaries (Neptune, workers).

**Consistent with LLM diagram palette** — same hex codes, different
semantic mapping. Both diagram sets can coexist in the same Excalidraw
instance without color conflicts.

## 3. Element schema (primitives)

Same three primitives as the LLM diagrams. Copy from any `gen_*.py`:

```python
BASE = {
    "version": 1, "isDeleted": False, "fillStyle": "solid",
    "strokeWidth": 2, "strokeStyle": "solid", "roughness": 1,
    "opacity": 100, "angle": 0, "strokeColor": "#1e1e1e",
    "groupIds": [], "frameId": None, "boundElements": [],
    "updated": 1775829200000, "link": None, "locked": False,
}
```

Three primitives:
- `rect(x, y, w, h, color, label=None, font_size=14)` — box with optional contained text
- `text(x, y, label, font_size=12, color="#1e1e1e")` — standalone annotation
- `arrow(x1, y1, x2, y2, dashed=False)` — directed connection

Rules:
- Rectangles: `"roundness": {"type": 3}`, fontFamily `5`
- Contained text: `containerId` + parent `boundElements` (bidirectional link)
- Arrows: `"roundness": {"type": 2}`, `"endArrowhead": "arrow"`, relative points
- Unique IDs: monotonic counter → `elem_NNNN`
- Multiline labels: `"\n"` in label string, adjust `text_h = font_size * 1.25 * lines`
- Dashed frames: set `strokeStyle: "dashed"`, `strokeColor: "#868e96"` after creation

## 4. Component templates

### 4a. Server / Service box
```python
rect(x, y, 400, 55, YELLOW,
     "Queue Server (server.py)\nTCP :9999 · JSON-RPC · SQLite-backed", font_size=13)
```
- Width: 350–480 depending on label length
- Height: 55 for 2-line, 40 for 1-line
- Color: YELLOW for queue, GREEN for archive receiver

### 4b. Database box
```python
rect(x, y, 200, 40, PEACH, "app7.db", font_size=12)
text(x, y + 42, "16 data tables", font_size=10, color=GRAY)
```
- Always PEACH
- Annotation below with schema details

### 4c. Worker frame
```python
rect(x, y, 320, 210, "transparent", label=None, rounded=False)
elements[-1]["strokeStyle"] = "dashed"
elements[-1]["strokeColor"] = FRAME
text(x + 10, y + 8, "Worker 1 (homelab)", font_size=12, color=FRAME)
# Internal components:
rect(x + 30, y + 40, 260, 40, RED, "worker.py (poll loop)", font_size=12)
rect(x + 30, y + 95, 260, 40, RED, "drain.py (push loop)", font_size=12)
rect(x + 80, y + 155, 160, 35, PEACH, "app7.db", font_size=12)
```
- Dashed border, gray stroke
- Internal: worker.py (RED), drain.py (RED), db (PEACH)

### 4d. Neptune frame
```python
rect(x, y, 1100, 230, "transparent", label=None, rounded=False)
elements[-1]["strokeStyle"] = "dashed"
elements[-1]["strokeColor"] = FRAME
text(x + 10, y + 8, "Neptune (Digital Ocean VPS)", font_size=14, color=FRAME)
# Contains: Queue Server + Archive Receiver side by side
```

### 4e. NAT boundary
```python
arrow(80, y, 1280, y, dashed=True)
elements[-1]["endArrowhead"] = None  # line, not arrow
text(cx - 60, y - 18, "═══  NAT Boundary  ═══", font_size=13, color=FRAME)
```

### 4f. Pipeline stage
```python
text(LABEL_X, y + 10, "Stage N", font_size=14, color=FRAME)
rect(STAGE_X, y, STAGE_W, 55, COLOR,
     "Stage description\ndetail line", font_size=13)
text(STAGE_X + STAGE_W + 15, y + 8, "annotation", font_size=10, color=GRAY)
arrow(CX, y + 55, CX, y + 75)  # to next stage
```

### 4g. Protocol exchange (two-column)
```python
# Left column: sender
rect(LEFT_CX - 170, y, 340, 65, LAVENDER,
     "Send HEADER (16 bytes)\npayload_size | row_count | table_id | flags")
# Right column: receiver
rect(RIGHT_CX - 160, y, 320, 65, GREEN,
     "Parse HEADER\nEvaluate admission")
# Horizontal arrow between
arrow(LEFT_CX + 170, y + 32, RIGHT_CX - 160, y + 32)
text(MID_CX - 30, y + 14, "16 bytes →", font_size=11, color=GRAY)
```

## 5. Diagram types

### Overview diagrams
- Show all system components
- Use dashed frames for boundaries (Neptune, workers, NAT)
- Fan-out arrows from server to multiple workers
- Converging arrows from workers to collector
- Legend + design properties on the right

### Flow diagrams
- Step-by-step vertical sequence (numbered ① ② ③...)
- One column for main flow, annotations on the right
- State/lifecycle diagram in the right margin
- Each step is a colored box with arrow to next

### Protocol diagrams
- Two-column layout (sender left, receiver right)
- Dashed vertical divider between columns
- Horizontal arrows show message exchange direction
- Format variants shown as side-by-side boxes below

### Internal diagrams
- Single component frame (dashed border)
- Multiple subsystems inside (poll loop, drain loop)
- Local databases shown with schema annotations
- tmux deployment layout at bottom right

### Pipeline diagrams
- Numbered stages in vertical sequence
- Annotations column on the right
- Detail sections (modes, dedup, schema) in right margin
- Command reference at bottom

## 6. Generator step-by-step (the recipe)

Given a new view of the architecture to diagram:

1. **Pick the closest reference** from the table in §0.
2. **Copy its generator** to a new `gen_<name>.py`.
3. **Adapt the title block** (§4 header pattern):
   - Title: what this diagram shows
   - Config: key parameters/ports/protocols
   - Subtitle: design principles and constraints
4. **Build the main flow** top-to-bottom:
   - Identify the primary data path
   - Place components as colored boxes
   - Connect with arrows
   - Add annotations to the right
5. **Add detail sections** in the right margin:
   - State machines, modes, schemas, commands
6. **Add legend** (right gutter).
7. **Run**: `python3 gen_<name>.py diagrams-instances/<name>.excalidraw`
8. **Validate**: check element count, verify JSON is valid.
9. **Open**: load in Excalidraw (local dev server), check for:
   - Overlapping elements
   - Arrow misalignment
   - Text overflow outside containers
   - Readable font sizes at default zoom
10. **Iterate**: adjust coordinates in 20 px increments.

## 7. Viewing the diagrams

### Option A: excalidraw-math-sync (recommended)
```bash
# Copy to drawings folder
cp diagrams-instances/*.excalidraw /home/b/excalidraw-math-sync/drawings/

# Start sync server + Excalidraw
cd /home/b/excalidraw-math-sync && just sync

# Open browser, select file from file picker
```

### Option B: Excalidraw web
1. Go to https://excalidraw.com
2. Open file → select `.excalidraw` file
3. View/edit in browser

### Option C: VS Code extension
Install the Excalidraw VS Code extension, open `.excalidraw` files directly.

## 8. Sizing

No element budget. Use as many elements as the architecture demands.
Current diagrams range from ~80 to ~120 elements. Complex views with
full table schemas, all 16 tables, or detailed protocol byte layouts
may reach 200+ elements.

Typical sizes:
- Overview: 100–150 elements, 1500×1100 canvas
- Flow detail: 80–120 elements, 1200×1200 canvas
- Protocol: 80–100 elements, 1200×1400 canvas (tall for sequence)
- Internals: 100–130 elements, 1300×1200 canvas
- Pipeline: 100–120 elements, 1400×1100 canvas

## 9. Common pitfalls

- **Text overflow**: keep container width ≥ `len(label) * font_size * 0.6 + 16`
- **Arrow points wrong**: points array is relative to arrow's `x,y`
- **Broken containerId**: rect `boundElements` and text `containerId` must match
- **Overlapping frames**: worker frames need W_GAP ≥ 40 px between them
- **NAT boundary obscured**: keep 30 px clear above and below the line
- **Too many arrows crossing**: use trunk-and-branch pattern — one main
  vertical line, then horizontal branches to targets
- **Annotations cluttering flow**: keep all annotations to the RIGHT of
  main flow, never inline between pipeline stages

## 10. Adding a new architecture component

When the system gains a new component (e.g., a new service, a new worker type):

1. Update `gen_system_overview.py` first — it's the canonical view
2. Create a detail diagram if the component has internal complexity
3. Update `gen_collection_pipeline.py` if data flow changes
4. Re-run all generators to produce fresh `.excalidraw` files
5. Copy to excalidraw-math-sync for viewing if desired

## 11. File inventory

```
auto-docs/architecture/
├── ARCHITECTURE_DIAGRAM_GUIDE.md     ← this file
├── gen_system_overview.py            ← full system topology
├── gen_job_queue_flow.py             ← TCP :9999 detail
├── gen_archive_drain_flow.py         ← TCP :8080 detail
├── gen_worker_internals.py           ← worker node internals
├── gen_collection_pipeline.py        ← 7-stage pipeline
└── diagrams-instances/
    ├── system-overview.excalidraw
    ├── job-queue-flow.excalidraw
    ├── archive-drain-flow.excalidraw
    ├── worker-internals.excalidraw
    └── collection-pipeline.excalidraw
```

## 12. Regenerating all diagrams

```bash
cd /home/b/simple-tcp-comm/auto-docs/architecture
python3 gen_system_overview.py      diagrams-instances/system-overview.excalidraw
python3 gen_job_queue_flow.py       diagrams-instances/job-queue-flow.excalidraw
python3 gen_archive_drain_flow.py   diagrams-instances/archive-drain-flow.excalidraw
python3 gen_worker_internals.py     diagrams-instances/worker-internals.excalidraw
python3 gen_collection_pipeline.py  diagrams-instances/collection-pipeline.excalidraw
```

Or one-liner:
```bash
for gen in gen_*.py; do
  name=$(echo "$gen" | sed 's/gen_//;s/.py//')
  python3 "$gen" "diagrams-instances/${name//_/-}.excalidraw"
done
```
