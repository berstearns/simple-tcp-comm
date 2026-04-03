# Worker Deployment Instructions

Step-by-step guide for deploying workers on a new machine. Intended for LLM agents performing automated deployments.

## Architecture Overview

```
                        ┌─────────────────────┐
                        │   Queue Server (DO)  │
                        │   server.py :9999    │
                        │   jobs.db (queue)    │
                        └─────┬───────┬───────┘
                              │       │
                    TCP/9999  │       │  TCP/9999
                              │       │
               ┌──────────────┘       └──────────────┐
               ▼                                     ▼
    ┌─────────────────────┐              ┌─────────────────────┐
    │   Worker (home lab)  │              │   Worker (other)    │
    │   worker.py          │              │   worker.py         │
    │   /var/lib/myapp/    │              │   /var/lib/myapp/   │
    │     main.db          │              │     main.db         │
    │     logs.db          │              │     logs.db         │
    └─────────────────────┘              └─────────────────────┘
```

- **Server** (`server.py`): runs on a remote VPS, accepts jobs over TCP, stores queue in `jobs.db`.
- **Workers** (`worker.py`): run on local/edge machines, poll the server for jobs, execute SQL queries against local SQLite databases.
- **Supervisor** (`supervisor.sh`): keeps the worker alive, auto-updates from git, runs in a tmux session via `start_supervisor.sh`.

## Prerequisites

- Linux machine (Debian/Ubuntu, Arch, Fedora)
- SSH access with sudo
- Git repo cloned to the machine

## Step 1: Clone the Repository

```bash
git clone <REPO_URL> ~/simple-tcp-comm
cd ~/simple-tcp-comm
```

If already cloned, ensure it's up to date:

```bash
cd ~/simple-tcp-comm
git pull origin main
```

## Step 2: Run Infrastructure Setup

This creates database directories, initializes schemas, installs dependencies, and ensures `.env` is configured.

```bash
sudo ./infrastructure.sh
```

To verify without making changes:

```bash
./infrastructure.sh --check
```

### What `infrastructure.sh` does

1. Installs system packages: `python3`, `sqlite3`, `tmux`, `git`
2. Creates `/var/lib/myapp/` directory with correct ownership
3. Creates `main.db` with `users` table schema
4. Creates `logs.db` with `events` table schema
5. Adds `QUEUE_DBS` to `.env` if missing
6. Makes all shell scripts executable

## Step 3: Configure `.env`

Edit `.env` in the repo root. Required variables:

```bash
# Server connection (the queue server's public IP and port)
QUEUE_HOST=137.184.225.153
QUEUE_PORT=9999

# Worker polling interval in seconds
QUEUE_POLL=2

# Local database paths — must match what infrastructure.sh created
QUEUE_DBS=main=/var/lib/myapp/main.db,logs=/var/lib/myapp/logs.db
```

Optional variables (set in environment or `.env`):

```bash
# Unique name for this worker (defaults to hostname)
WORKER_NAME=my-home-lab

# Supervisor settings (usually fine as defaults)
DEPLOY_BRANCH=main           # git branch to track
UPDATE_INTERVAL=300          # seconds between git pull checks
GRACE_TIMEOUT=60             # seconds to wait for worker shutdown
```

### Variable reference

| Variable | Default | Used by | Description |
|---|---|---|---|
| `QUEUE_HOST` | `127.0.0.1` | worker, client | Queue server IP |
| `QUEUE_PORT` | `9999` | worker, client, server | TCP port |
| `QUEUE_POLL` | `2` | worker | Seconds between polls |
| `QUEUE_DBS` | `main=/var/lib/myapp/main.db,logs=/var/lib/myapp/logs.db` | worker, migrate.sh | Comma-separated `name=path` pairs |
| `WORKER_NAME` | `hostname` | worker | Worker identifier |
| `DEPLOY_BRANCH` | `main` | supervisor | Git branch to auto-update from |
| `UPDATE_INTERVAL` | `300` | supervisor | Seconds between update checks |
| `GRACE_TIMEOUT` | `60` | supervisor | Max seconds to wait for graceful shutdown |
| `QUEUE_DB` | `jobs.db` | server | Queue database path (server only) |

## Step 4: Start the Worker

Launch the supervisor in a detached tmux session:

```bash
./start_supervisor.sh
```

This runs `supervisor.sh` inside a tmux session named `worker-supervisor`.

### What happens on start

1. `supervisor.sh` starts `worker.py` as a background process
2. Worker connects to the queue server at `QUEUE_HOST:QUEUE_PORT`
3. Worker polls for jobs every `QUEUE_POLL` seconds
4. Every `UPDATE_INTERVAL` seconds, supervisor checks git for updates
5. If an update is found: stops worker, pulls code, runs `migrate.sh`, restarts worker

### Managing the session

```bash
# Attach to see live output
tmux attach -t worker-supervisor

# Detach without stopping: press Ctrl-B then D

# Stop the worker and supervisor
tmux kill-session -t worker-supervisor

# Check if running
tmux has-session -t worker-supervisor 2>/dev/null && echo "running" || echo "stopped"
```

## Step 5: Verify

### Check worker is running

```bash
tmux attach -t worker-supervisor
# You should see: worker '<name>' v<hash> polling <ip>:<port> every 2s
```

### Submit a test job from the client

From any machine with access to the queue server:

```bash
python3 client.py ping
python3 client.py query main "SELECT count(*) FROM users"
python3 client.py query logs "SELECT count(*) FROM events"
```

### Check job results

```bash
python3 client.py status <JOB_ID>
python3 client.py ls
```

### List registered workers

```bash
python3 client.py workers
```

## Troubleshooting

### "unable to open database file"

Database path doesn't exist or wrong permissions.

```bash
# Check
./infrastructure.sh --check

# Fix
sudo ./infrastructure.sh
```

### "down: [Errno 111] Connection refused, retry in 5s"

Worker can't reach the queue server.

```bash
# Verify server IP and port in .env
cat .env | grep QUEUE_HOST

# Test connectivity
python3 -c "import socket; s=socket.socket(); s.connect(('QUEUE_HOST_IP', 9999)); print('OK'); s.close()"
```

### Worker keeps restarting

Check supervisor logs in the tmux session. Common causes:
- Python not installed (`sudo ./infrastructure.sh` fixes this)
- `.env` has bad syntax
- Database file corrupted — delete and re-run `infrastructure.sh`

### Stale jobs stuck in "running" status

If a worker died mid-job:

```bash
python3 client.py reset <JOB_ID>
```

## Database Schemas

### main.db — `users` table

```sql
CREATE TABLE users(
    id INTEGER PRIMARY KEY,
    name TEXT,
    email TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### logs.db — `events` table

```sql
CREATE TABLE events(
    id INTEGER PRIMARY KEY,
    type TEXT,
    msg TEXT,
    ts DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

New tables or columns should be added to `migrate.sh` as idempotent migrations. The supervisor runs `migrate.sh` automatically after every git update.

## Full Deployment Checklist

```
[ ] Machine has internet + SSH access
[ ] Repo cloned and on correct branch
[ ] sudo ./infrastructure.sh completed without errors
[ ] .env has correct QUEUE_HOST (server's public IP)
[ ] .env has QUEUE_DBS pointing to existing database files
[ ] ./infrastructure.sh --check passes all checks
[ ] ./start_supervisor.sh launched successfully
[ ] tmux attach shows worker polling
[ ] python3 client.py ping returns a job ID
[ ] python3 client.py workers shows this worker
```
