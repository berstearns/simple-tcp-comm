# Deployment Rules — THESE RULES MUST BE ENFORCED

> Created: 2026-04-13
> Applies to: every machine running simple-tcp-comm components

---

## THIS IS NOT OPTIONAL

Every rule below is load-bearing. If you skip a naming convention, health checks
break. If you skip a pane title, restart scripts target the wrong process. If you
use a different session name, the entire ops toolchain goes blind.

**Do not improvise. Do not rename. Do not "temporarily" skip a step.**

---

## Rule 1: Every Component Runs in a Named tmux Session

There are exactly **2 session names** in the entire system:

| Machine type | Session name | Purpose |
|-------------|-------------|---------|
| Server (neptune) | `stcp` | queue server + archive receiver |
| Worker device | `stcp-w` | job worker + drain process |

**Violations:**
- Running a component outside tmux = invisible to health checks = does not exist
- Using a different session name = invisible to health checks = does not exist
- Running two sessions with different names on the same machine = forbidden

---

## Rule 2: Every Window Has a Fixed Name

| Session | Window name | What runs inside |
|---------|------------|-----------------|
| `stcp` | `queue` | `python3 server.py` |
| `stcp` | `archive` | `python3 archive_receiver/json_zlib/receiver.py` |
| `stcp-w` | `worker` | `python3 workers/app7/worker.py` |
| `stcp-w` | `drain` | `python3 archive_receiver/json_zlib/drain.py` |

**Violations:**
- Adding extra windows to these sessions = allowed but they must not use reserved names
- Renaming a window = restart scripts and health checks break

---

## Rule 3: Every Pane Has a Title Set via `select-pane -T`

| Session | Window | Pane title |
|---------|--------|-----------|
| `stcp` | `queue` | `queue-server` |
| `stcp` | `archive` | `archive-receiver` |
| `stcp-w` | `worker` | `job-worker` |
| `stcp-w` | `drain` | `drain-push` |

**Why:** `tmux list-panes -F '#{pane_title}'` is the only way to know what's running
without parsing `ps` output. The title is set once at startup and survives process restarts
inside the pane.

**Violations:**
- Skipping `-T` on pane creation = health check reports "unnamed" = ambiguous

---

## Rule 4: Startup Order

```
NEPTUNE (server side):
  1. stcp:queue      — server.py MUST be up before any worker connects
  2. stcp:archive    — receiver.py MUST be up before any drain connects

WORKER (each device):
  1. stcp-w:worker   — worker.py starts polling queue
  2. stcp-w:drain    — drain.py starts pushing to archive receiver
```

**The queue server must be running before workers start.
The archive receiver must be running before drains start.
Starting in wrong order = connection refused errors in logs.**

---

## Rule 5: One .env File Per Worker Device

Every worker device has exactly one `.env` file that configures both worker.py and drain.py.

**Required variables:**

```bash
# .env — EVERY variable below is required, no defaults are safe
QUEUE_HOST=137.184.225.153       # neptune IP (DO droplet)
QUEUE_PORT=9999                  # queue server port
QUEUE_POLL=2                     # poll interval seconds
QUEUE_DBS=app7=/absolute/path/to/app7.db   # db name=path mapping
WORKER_NAME=<machine-hostname>   # unique per device, used in archive _source_worker
```

**The drain extracts its config from these same variables at startup.**

**Violations:**
- Relative paths in QUEUE_DBS = breaks when cwd changes
- Reusing WORKER_NAME across devices = archive data gets mixed, cannot distinguish sources
- Missing WORKER_NAME = defaults to "drain-worker" which collides across devices

---

## Rule 6: Neptune Environment

Neptune does NOT use a `.env` file. Its config is passed inline or via defaults:

```
server.py:   QUEUE_DB=jobs.db (default)    — port 9999 (hardcoded)
receiver.py: ARCHIVE_DB=/data/archive.db   — ARCHIVE_PORT=8080 (default)
```

**The ARCHIVE_DB path must be absolute and on a partition with >100MB free.**
Receiver rejects all connections when disk free drops below 100MB.

---

## Rule 7: Port Allocation (non-negotiable)

| Port | Protocol | Component | Direction |
|------|----------|-----------|-----------|
| 9999 | TCP, 4-byte len + JSON | server.py (queue) | neptune listens, workers connect |
| 8080 | TCP, binary 16B header protocol | receiver.py (archive) | neptune listens, drains connect |

**Both ports must be open in the DO firewall for worker IPs.**

---

## Rule 8: Health Check Is the Source of Truth

**The canonical "is everything running?" command:**

```bash
# On neptune:
tmux list-panes -t stcp -a -F '#{window_name}:#{pane_title} pid=#{pane_pid} cmd=#{pane_current_command}'

# Expected output (both lines, both showing python3):
#   queue:queue-server pid=12345 cmd=python3
#   archive:archive-receiver pid=12346 cmd=python3
```

```bash
# On worker:
tmux list-panes -t stcp-w -a -F '#{window_name}:#{pane_title} pid=#{pane_pid} cmd=#{pane_current_command}'

# Expected output (both lines, both showing python3):
#   worker:job-worker pid=23456 cmd=python3
#   drain:drain-push pid=23457 cmd=python3
```

**If `cmd=` shows `bash` or `zsh` instead of `python3`, the process has crashed.**
The pane is still alive but the component is dead. Restart it.

---

## Rule 9: Restart = send C-c Then Re-run

Never kill the tmux pane to restart. Send Ctrl-C to stop the process, then re-send
the command. The pane title survives. The window name survives. Only the process restarts.

```bash
# Restart queue server:
tmux send-keys -t stcp:queue C-c
sleep 1
tmux send-keys -t stcp:queue "python3 server.py" C-m

# Restart archive receiver:
tmux send-keys -t stcp:archive C-c
sleep 1
tmux send-keys -t stcp:archive "ARCHIVE_DB=/data/archive.db python3 archive_receiver/json_zlib/receiver.py" C-m

# Restart job worker:
tmux send-keys -t stcp-w:worker C-c
sleep 1
tmux send-keys -t stcp-w:worker "set -a; source .env; set +a; python3 workers/app7/worker.py" C-m

# Restart drain:
tmux send-keys -t stcp-w:drain C-c
sleep 1
tmux send-keys -t stcp-w:drain "WORKER_DB=\$WORKER_DB ARCHIVE_HOST=\$QUEUE_HOST ARCHIVE_PORT=8080 WORKER_NAME=\$WORKER_NAME python3 archive_receiver/json_zlib/drain.py" C-m
```

**Violations:**
- `tmux kill-pane` = loses pane title, need to recreate with `-T`
- `tmux kill-window` = need to recreate window + pane + title
- `tmux kill-session` = nuclear option, only use `*_start.sh` to rebuild

---

## Rule 10: Full Teardown and Rebuild

When everything is broken and you need to start clean:

```bash
# Neptune:
ssh neptune 'cd /root/simple-tcp-comm && bash auto-docs/deploy/neptune_start.sh'

# Worker:
bash auto-docs/deploy/worker_start.sh /home/b/simple-tcp-comm .env
```

These scripts enforce all naming rules automatically. If you can't remember the rules,
just run the script.

---

## Quick Reference Card

```
 NEPTUNE                                    WORKER DEVICE
 ═══════                                    ═════════════
 session: stcp                              session: stcp-w
 ├── window: queue                          ├── window: worker
 │   └── pane: queue-server                 │   └── pane: job-worker
 │       python3 server.py                  │       python3 workers/app7/worker.py
 │       :9999                              │       polls :9999 every 2s
 └── window: archive                        └── window: drain
     └── pane: archive-receiver                 └── pane: drain-push
         python3 .../receiver.py                    python3 .../drain.py
         :8080                                      pushes :8080 every 300s

 health: tmux list-panes -t stcp -a ...     health: tmux list-panes -t stcp-w -a ...
 attach: tmux a -t stcp                     attach: tmux a -t stcp-w
```
