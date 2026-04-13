# Deploy — Strict tmux Deployment for simple-tcp-comm

> Created: 2026-04-13

## THESE RULES MUST BE ENFORCED

Read [RULES.md](RULES.md) before touching anything. Every session name, window
name, and pane title is load-bearing. The health check script depends on them.

## Files

### Rules & Scripts

| File | What it does | Run where |
|------|-------------|-----------|
| [RULES.md](RULES.md) | All naming rules and conventions — **read first** | (reference) |
| [neptune_start.sh](neptune_start.sh) | Creates `stcp` session with queue + archive | neptune |
| [worker_start.sh](worker_start.sh) | Creates `stcp-w` session with worker + drain | worker device |
| [health_check.sh](health_check.sh) | Checks all panes are alive and named correctly | any machine |

### Per-Component Execution Docs

Each doc covers: identity, what it does, env vars, prerequisites, deploy steps
(fresh / restart / rebuild), verify, logs, failure modes, and dependencies.

| # | File | Component | Startup order |
|---|------|-----------|---------------|
| 1 | [execution-queue-server.md](execution-queue-server.md) | `stcp:queue:queue-server` — server.py :9999 | **first** |
| 2 | [execution-archive-receiver.md](execution-archive-receiver.md) | `stcp:archive:archive-receiver` — receiver.py :8080 | second |
| 3 | [execution-job-worker.md](execution-job-worker.md) | `stcp-w:worker:job-worker` — worker.py | third |
| 4 | [execution-drain.md](execution-drain.md) | `stcp-w:drain:drain-push` — drain.py | **last** |

## Quick Start

```bash
# 1. Neptune (ssh into DO box first)
ssh neptune
cd /root/simple-tcp-comm
bash auto-docs/deploy/neptune_start.sh

# 2. Worker (on local machine)
bash auto-docs/deploy/worker_start.sh /home/b/simple-tcp-comm .env

# 3. Verify everything
bash auto-docs/deploy/health_check.sh all
```

## Naming Map

```
 NEPTUNE  stcp                  WORKER  stcp-w
 ├── queue:queue-server         ├── worker:job-worker
 └── archive:archive-receiver   └── drain:drain-push
```
