# Deploy a Fresh Worker via tmux send-keys

> Verified 2026-04-13 on `archlinux` (bernardo-pc). All commands executed via `tmux send-keys` to a named pane.

## Context

This deploys a self-contained worker instance from a **git clone** — no file copying, no symlinks. The worker runs from its own cloned repo with its own `.env` and its own `dbs/` folder. Kill the pane, delete the folder, it's gone.

Used for: spinning up local test workers, deploying to remote machines, or running multiple workers side-by-side with different configs.

## Prerequisites

- tmux session exists with a named pane (e.g., `worker-YYYYMMDD`)
- Git repo is pushed and up to date (`git push origin main`)
- DO queue server running at `137.184.225.153:9999`
- Your IP is in the DO firewall

## The Commands (copy-paste ready)

### Variables (set these first)

```bash
TS=20260413                                          # timestamp tag
PANE="%48"                                           # tmux pane ID (find with: tmux list-panes -F '#{pane_id} #{pane_title}')
DIR="/home/b/simple-tcp-comm-worker-${TS}"           # local path
REPO="https://github.com/berstearns/simple-tcp-comm.git"
QUEUE_HOST="137.184.225.153"
```

### Step 1: Git clone

```bash
tmux send-keys -t ${PANE} "git clone ${REPO} ${DIR} && echo 'cloned'" C-m
```

### Step 2: Write .env

```bash
tmux send-keys -t ${PANE} "cat > ${DIR}/.env <<'ENVEOF'
QUEUE_HOST=${QUEUE_HOST}
QUEUE_PORT=9999
QUEUE_POLL=2
QUEUE_DBS=app7=${DIR}/dbs/app7.db
WORKER_NAME=worker-${TS}
ENVEOF" C-m
```

### Step 3: Create dbs dir, source env, start worker

```bash
tmux send-keys -t ${PANE} "mkdir -p ${DIR}/dbs" C-m
tmux send-keys -t ${PANE} "unset QUEUE_HOST QUEUE_PORT QUEUE_POLL QUEUE_DBS WORKER_NAME; set -a; source ${DIR}/.env; set +a; cd ${DIR} && python3 workers/app7-explicit-db-hierarchy_20260409_154552/worker.py" C-m
```

### Step 4: Verify (from any terminal)

```bash
# Check pane is running
tmux capture-pane -t ${PANE} -p -S -5

# Check worker registered on queue
python3 /home/b/simple-tcp-comm/client.py workers | grep "worker-${TS}"
```

## All-in-one (single block)

```bash
TS=20260413
PANE="%48"
DIR="/home/b/simple-tcp-comm-worker-${TS}"
REPO="https://github.com/berstearns/simple-tcp-comm.git"
QUEUE_HOST="137.184.225.153"

tmux send-keys -t ${PANE} "git clone ${REPO} ${DIR} && echo 'cloned'" C-m

# Wait for clone to finish before sending next commands
sleep 5

tmux send-keys -t ${PANE} "cat > ${DIR}/.env <<'ENVEOF'
QUEUE_HOST=${QUEUE_HOST}
QUEUE_PORT=9999
QUEUE_POLL=2
QUEUE_DBS=app7=${DIR}/dbs/app7.db
WORKER_NAME=worker-${TS}
ENVEOF" C-m

tmux send-keys -t ${PANE} "mkdir -p ${DIR}/dbs && unset QUEUE_HOST QUEUE_PORT QUEUE_POLL QUEUE_DBS WORKER_NAME && set -a && source ${DIR}/.env && set +a && cd ${DIR} && python3 workers/app7-explicit-db-hierarchy_20260409_154552/worker.py" C-m
```

## What happens

1. **git clone** — full repo at `~/simple-tcp-comm-worker-YYYYMMDD/`, commit `5fcbf5f`
2. **.env written** — `WORKER_NAME=worker-YYYYMMDD`, DB at `${DIR}/dbs/app7.db`
3. **unset stale vars** — critical if the pane previously sourced a different `.env`
4. **source .env** — `set -a` exports all vars
5. **worker.py starts** — applies schema from the cloned repo's `dbs/.../head_schema/schema.sql`, creates `app7.db`, begins polling

## Expected output in the pane

```
Cloning into '/home/b/simple-tcp-comm-worker-20260413'...
remote: Enumerating objects: 231, done.
...
cloned
  app7: schema applied from .../dbs/app7-explicit-db-hierarchy_.../head_schema/schema.sql
app7-worker 'worker-20260413-app7-hierarchy-verify' v5fcbf5f polling 137.184.225.153:9999 every 2s
  dbs: {'app7': '/home/b/simple-tcp-comm-worker-20260413/dbs/app7.db'}
waiting 2 seconds.
waiting 2 seconds.
```

## Result on disk

```
~/simple-tcp-comm-worker-20260413/
├── .env                    ← queue config for this instance
├── .git/                   ← full repo history
├── env.py                  ← .env loader (from repo)
├── client.py               ← TCP client (from repo)
├── archive_receiver/       ← drain + receiver variants (from repo)
├── archive_receiver/       ← all receiver variants (from repo)
├── workers/
│   └── app7-explicit-db-hierarchy_.../
│       └── worker.py       ← the worker that's running
└── dbs/
    ├── app7-explicit-db-hierarchy_.../
    │   └── head_schema/
    │       └── schema.sql  ← DDL (from repo)
    └── app7.db             ← auto-created on first run
```

## Adapting for a remote server (e.g., DO droplet, homelab box)

Same commands, different `DIR` and `PANE`. SSH in, create a tmux session, name a pane, and run:

```bash
# On the remote machine
TS=$(date +%Y%m%d)
DIR="/root/simple-tcp-comm-worker-${TS}"
REPO="https://github.com/berstearns/simple-tcp-comm.git"

# If using tmux locally to send to a remote pane via SSH:
ssh root@<REMOTE_IP> "
  git clone ${REPO} ${DIR}
  mkdir -p ${DIR}/dbs
  cat > ${DIR}/.env <<'ENVEOF'
QUEUE_HOST=137.184.225.153
QUEUE_PORT=9999
QUEUE_POLL=2
QUEUE_DBS=app7=${DIR}/dbs/app7.db
WORKER_NAME=worker-${TS}-$(hostname)
ENVEOF
"

# Then start in a remote tmux (so it survives disconnect):
ssh root@<REMOTE_IP> "
  tmux new-session -d -s worker -n main
  tmux send-keys -t worker 'unset QUEUE_HOST QUEUE_PORT QUEUE_POLL QUEUE_DBS WORKER_NAME; set -a; source ${DIR}/.env; set +a; cd ${DIR} && python3 workers/app7-explicit-db-hierarchy_20260409_154552/worker.py' C-m
"
```

### DO droplet example (using deploy tools)

```bash
DO_DROPLET=ubuntu-s-1vcpu-1gb-amd-sfo3-01 \
DO_SSH_PASS_FILE=/home/b/dopass \
/home/b/p/all-my-tiny-projects/do-automation/job-queue/deploy-queue setup

# Or manually:
DO_SSH_PASS_FILE=/home/b/dopass sshpass -p "$(head -1 /home/b/dopass)" \
  ssh root@137.184.225.153 "
    TS=\$(date +%Y%m%d)
    DIR=/root/simple-tcp-comm-worker-\${TS}
    git clone https://github.com/berstearns/simple-tcp-comm.git \${DIR}
    mkdir -p \${DIR}/dbs
    cat > \${DIR}/.env <<ENVEOF
QUEUE_HOST=127.0.0.1
QUEUE_PORT=9999
QUEUE_POLL=2
QUEUE_DBS=app7=\${DIR}/dbs/app7.db
WORKER_NAME=neptune-worker-\${TS}
ENVEOF
    tmux new-session -d -s worker
    tmux send-keys -t worker 'set -a; source \${DIR}/.env; set +a; cd \${DIR} && python3 workers/app7-explicit-db-hierarchy_20260409_154552/worker.py' C-m
  "
```

Note: on the DO box, `QUEUE_HOST=127.0.0.1` since the queue server runs on the same machine.

## Gotchas

| Issue | Fix |
|---|---|
| Worker shows wrong name/DB path | Stale env vars from a previous `source`. Always `unset` first. |
| `env.py` not found | `cd` into the repo root before running `worker.py` |
| Schema not found | Worker resolves schema relative to `worker.py`'s location in the repo tree. Don't move `worker.py` out of `workers/`. |
| Multiple workers grabbing each other's jobs | Queue is FIFO with no target routing. All workers compete. This is by design — jobs go to whoever polls first. |
| Clone fails (auth) | Repo must be public, or set up SSH keys / personal access token. |

## Naming convention

| Resource | Name |
|---|---|
| tmux pane title | `worker-YYYYMMDD` |
| folder | `~/simple-tcp-comm-worker-YYYYMMDD/` |
| WORKER_NAME in .env | `worker-YYYYMMDD` |
| Registered on queue as | `worker-YYYYMMDD-app7-hierarchy-verify` (suffix added by worker.py) |
| Worker DB | `~/simple-tcp-comm-worker-YYYYMMDD/dbs/app7.db` |
