# Local E2E Deployment — Worker + Collector in a Single tmux Session

Full setup for verifying the real Android app → DO queue → local worker → offline collector pipeline. You open one tmux session, launch the app, tap around, and watch data flow through every stage.

## Architecture

```
┌──────────────────────┐         ┌──────────────────────────┐
│  Android Emulator    │         │  DO Queue Server         │
│  pl.czak.imageviewer │  TCP    │  137.184.225.153:9999    │
│  .app7               │ ──────► │  server.py               │
│  Room DB             │         │  jobs.db                 │
│  (auto-sync 60s)     │         └───────────┬──────────────┘
└──────────────────────┘                     │  poll every 2s
                                             ▼
                              ┌──────────────────────────────┐
                              │  tmux: app7-e2e              │
                              │                              │
                              │  PANE 0 (top): worker        │
                              │    worker.py polling queue   │
                              │    writes → dbs/TS/app7.db   │
                              │                              │
                              │  PANE 1 (bottom): collector  │
                              │    collector.py loop (60s)   │
                              │    reads worker DB           │
                              │    writes → offline-         │
                              │    collected/TS/archive.db   │
                              └──────────────────────────────┘
```

## Prerequisites

- DO queue server running (`deploy-queue status` → RUNNING)
- Your IP in the DO firewall (`do-firewall add-ip <fw-id> $(curl -s ifconfig.me)`)
- Android emulator booted with app7 APK installed
- Auto-sync enabled in the app (Settings toggle or launch with `--ez auto_sync true`)

## Directory Layout

```
/home/b/simple-tcp-comm-worker-deploy/
├── .env.e2e-YYYYMMDD_HHMMSS          ← worker env for this run
├── dbs/
│   └── YYYYMMDD_HHMMSS/
│       └── app7.db                    ← worker writes here
└── offline-collected/
    └── YYYYMMDD_HHMMSS/
        └── archive.db                 ← collector writes here
```

Every run gets its own timestamp. Old runs are never touched.

## Setup — One Command

```bash
/home/b/simple-tcp-comm/setup_e2e_local.sh
```

This script does everything below automatically. If you prefer manual control, follow the step-by-step instead.

## Step-by-Step (Manual)

### 1. Generate timestamp and create directories

```bash
TS=$(date +%Y%m%d_%H%M%S)
echo "Run timestamp: $TS"

mkdir -p /home/b/simple-tcp-comm-worker-deploy/dbs/${TS}
mkdir -p /home/b/simple-tcp-comm-worker-deploy/offline-collected/${TS}
```

### 2. Write the env file

```bash
cat > /home/b/simple-tcp-comm-worker-deploy/.env.e2e-${TS} <<EOF
QUEUE_HOST=137.184.225.153
QUEUE_PORT=9999
QUEUE_POLL=2
QUEUE_DBS=app7=/home/b/simple-tcp-comm-worker-deploy/dbs/${TS}/app7.db
WORKER_NAME=e2e-${TS}
EOF
```

### 3. Kill any previous E2E session

```bash
tmux kill-session -t app7-e2e 2>/dev/null
```

### 4. Create tmux session with 2 named panes

```bash
# Create session with first window named "pipeline"
tmux new-session -d -s app7-e2e -n pipeline -c /home/b/simple-tcp-comm

# Split horizontally: top = worker (pane 0), bottom = collector (pane 1)
tmux split-window -t app7-e2e:pipeline -v -c /home/b/simple-tcp-comm
```

### 5. Start worker in pane 0 (top)

```bash
tmux send-keys -t app7-e2e:pipeline.0 \
  "echo '=== WORKER === run: ${TS}'; \
   set -a; source /home/b/simple-tcp-comm-worker-deploy/.env.e2e-${TS}; set +a; \
   python3 workers/app7-explicit-db-hierarchy_20260409_154552/worker.py" C-m
```

### 6. Start collector loop in pane 1 (bottom)

```bash
tmux send-keys -t app7-e2e:pipeline.1 \
  "echo '=== COLLECTOR === run: ${TS} (60s cycle)'; \
   while true; do \
     echo '--- collect cycle \$(date +%H:%M:%S) ---'; \
     ARCHIVE_DB=/home/b/simple-tcp-comm-worker-deploy/offline-collected/${TS}/archive.db \
       python3 /home/b/simple-tcp-comm/collector.py collect \
         --direct /home/b/simple-tcp-comm-worker-deploy/dbs/${TS}/app7.db \
         --worker-name e2e-${TS}; \
     echo '--- verify ---'; \
     ARCHIVE_DB=/home/b/simple-tcp-comm-worker-deploy/offline-collected/${TS}/archive.db \
       python3 /home/b/simple-tcp-comm/collector.py verify \
         --direct /home/b/simple-tcp-comm-worker-deploy/dbs/${TS}/app7.db \
         --worker-name e2e-${TS}; \
     echo '--- sleeping 60s ---'; \
     sleep 60; \
   done" C-m
```

### 7. Verify worker registered

```bash
python3 /home/b/simple-tcp-comm/client.py workers | grep "e2e-${TS}"
```

## Using It

### Attach to the session

```bash
tmux attach -t app7-e2e
```

You see two panes:
- **Top**: worker polling the queue, printing `waiting 2 seconds.` or `ingesting...` lines
- **Bottom**: collector running every 60s, printing row counts and `OVERALL: PASS`

### Switch between panes

- `Ctrl-B ↑` — move to top pane (worker)
- `Ctrl-B ↓` — move to bottom pane (collector)
- `Ctrl-B D` — detach without stopping anything

### Launch the app with auto-sync

```bash
adb shell am start -n pl.czak.imageviewer.app7/pl.czak.learnlauncher.android.MainActivity --ez auto_sync true
```

### What to do

1. Open the app, browse comics, tap on pages, swipe between pages
2. Wait ~60s for auto-sync to fire (watch logcat or the worker pane)
3. The worker pane shows `ingesting... accepted=True counts={...}`
4. The collector pane shows `N new` rows on its next cycle
5. The `OVERALL: PASS (16/16)` line confirms archive matches worker

### Inspect data at any time

```bash
# Worker DB
sqlite3 /home/b/simple-tcp-comm-worker-deploy/dbs/YYYYMMDD_HHMMSS/app7.db \
  "SELECT comic_id, chapter_name FROM chapters; SELECT COUNT(*) FROM session_events;"

# Archive DB
sqlite3 /home/b/simple-tcp-comm-worker-deploy/offline-collected/YYYYMMDD_HHMMSS/archive.db \
  "SELECT _source_worker, COUNT(*) FROM session_events GROUP BY 1;"

# Collection log
ARCHIVE_DB=/home/b/simple-tcp-comm-worker-deploy/offline-collected/YYYYMMDD_HHMMSS/archive.db \
  python3 /home/b/simple-tcp-comm/collector.py status
```

### Check the DO queue audit trail

```bash
# Recent jobs (ingest + collector queries all visible)
python3 /home/b/simple-tcp-comm/client.py ls

# Specific job — shows payload, worker name, worker IP, result
python3 /home/b/simple-tcp-comm/client.py status <JOB_ID>
```

## Stopping

```bash
tmux kill-session -t app7-e2e
```

Data persists in the timestamped folders. Nothing is lost.

## Naming Convention

| Resource | Name | Why |
|----------|------|-----|
| tmux session | `app7-e2e` | One session to rule them all |
| tmux window | `pipeline` | The only window — worker + collector |
| pane 0 (top) | worker | Polls DO queue, ingests into local DB |
| pane 1 (bottom) | collector | 60s loop: collect + verify |
| worker name | `e2e-YYYYMMDD_HHMMSS` | Unique per run, visible on DO queue |
| worker DB | `dbs/YYYYMMDD_HHMMSS/app7.db` | Timestamped, never overwritten |
| archive DB | `offline-collected/YYYYMMDD_HHMMSS/archive.db` | Timestamped, never overwritten |
| env file | `.env.e2e-YYYYMMDD_HHMMSS` | One per run, full config snapshot |
