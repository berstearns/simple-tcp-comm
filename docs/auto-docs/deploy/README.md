# Deploy — Strict tmux Deployment for simple-tcp-comm

> Created: 2026-04-13, updated 2026-04-13
> THESE RULES MUST BE ENFORCED

Read [RULES.md](RULES.md) before touching anything. Every session name, window
name, and pane title is load-bearing. The health check script depends on them.

---

## Files

### Rules & Scripts

| File | What it does | Run where |
|------|-------------|-----------|
| [RULES.md](RULES.md) | All naming rules and conventions — **read first** | (reference) |
| [neptune_start.sh](neptune_start.sh) | Creates `stcp` session with queue + archive | neptune |
| [worker_start.sh](worker_start.sh) | Creates `stcp-w` session with worker + drain | worker device |
| [health_check.sh](health_check.sh) | Checks all panes are alive and named correctly | any machine |

### Per-Component Execution Docs (non-tmux, for `stcp`/`stcp-w` sessions)

| # | File | Component | Startup order |
|---|------|-----------|---------------|
| 1 | [execution-queue-server.md](execution-queue-server.md) | `stcp:queue:queue-server` — server.py :9999 | **first** |
| 2 | [execution-archive-receiver.md](execution-archive-receiver.md) | `stcp:archive:archive-receiver` — receiver.py :8080 | second |
| 3 | [execution-job-worker.md](execution-job-worker.md) | `stcp-w:worker:job-worker` — worker.py | third |
| 4 | [execution-drain.md](execution-drain.md) | `stcp-w:drain:drain-push` — drain.py | **last** |

### Per-Component Execution Docs (tmux send-keys, for git-clone worker deploys)

These use `tmux send-keys` to named panes — for deploying fresh worker instances
from a `git clone`. Each doc is self-contained with copy-paste commands.

| # | File | Component | Where |
|---|------|-----------|-------|
| 1 | [execution-queue-server-tmux.md](execution-queue-server-tmux.md) | Queue server on DO via ssh + tmux | neptune |
| 2 | [execution-archive-receiver-tmux.md](execution-archive-receiver-tmux.md) | **Archive receiver** — all 3 variants, user chooses | server |
| 3 | [execution-job-worker-tmux.md](execution-job-worker-tmux.md) | Job worker from git clone | worker device |
| 4 | [execution-archive-drain-tmux.md](execution-archive-drain-tmux.md) | **Archive drain** — must match receiver variant | worker device |
| 5 | [execution-timeline-tracker.md](execution-timeline-tracker.md) | Timeline tracker on worker DB | worker device |
| 6 | [execution-timeline-archive-tracker.md](execution-timeline-archive-tracker.md) | Timeline tracker on archive DB | server or worker |

---

## Archive Receiver Variants — Choose One

All 3 variants use the same binary protocol, same archive schema, same DB.
**The receiver and drain must use the same variant.**

| Variant | Flag | Receiver | Drain | When to use |
|---------|------|----------|-------|-------------|
| `json_plain` | `0x00` | `archive_receiver/json_plain/receiver.py` | `archive_receiver/json_plain/drain.py` | Debug, readable payloads |
| **`json_zlib`** | **`0x01`** | **`archive_receiver/json_zlib/receiver.py`** | **`archive_receiver/json_zlib/drain.py`** | **RECOMMENDED — production** |
| `struct_pack` | `0x02` | `archive_receiver/struct_pack/receiver.py` | `archive_receiver/struct_pack/drain.py` | Max throughput, rigid schema |

See [execution-archive-receiver-tmux.md](execution-archive-receiver-tmux.md) for
the full decision guide and variant tradeoffs.

---

## Quick Start

```bash
# 1. Neptune — queue server (ssh into DO box first)
ssh neptune
cd /root/simple-tcp-comm
bash auto-docs/deploy/neptune_start.sh

# 2. Neptune — archive receiver (pick a variant)
#    see execution-archive-receiver-tmux.md for all options

# 3. Worker — job worker + drain (on local machine)
bash auto-docs/deploy/worker_start.sh /home/b/simple-tcp-comm .env

# 4. Verify everything
bash auto-docs/deploy/health_check.sh all
```

## Naming Map

```
 NEPTUNE  stcp                  WORKER  stcp-w
 ├── queue:queue-server         ├── worker:job-worker
 └── archive:archive-receiver   └── drain:drain-push
```

## Startup Order — THESE RULES MUST BE ENFORCED

```
1. queue server   (neptune :9999)    ← everything depends on this
2. archive receiver (neptune :8080)  ← drains depend on this
3. job worker     (worker device)    ← polls queue, writes app7.db
4. archive drain  (worker device)    ← reads app7.db, pushes to receiver
```
