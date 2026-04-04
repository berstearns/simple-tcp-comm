# Implementation Overview

## Problem

The queue system routes jobs FIFO — any worker grabs any job. For the language learning app, each learner's data must live on a specific worker. Workers need backpressure when disk fills up. Data needs periodic archival.

## Architecture (current)

```
┌──────────────────────┐
│  Queue Server (DO)   │
│  server.py :9999     │
│  jobs.db             │
│  ├─ jobs table       │
│  └─ workers table    │
└──────┬───────┬───────┘
       │       │         TCP/9999, 4-byte len + JSON
       ▼       ▼
  Worker A   Worker B
  worker.py  worker.py
  main.db    main.db
  logs.db    logs.db
```

- **Protocol**: raw TCP, 4-byte big-endian length header + JSON. No HTTP.
- **Server ops**: submit, poll, ack, status, list, delete, reset, workers
- **Worker jobs**: query (SQL on local SQLite), exec (shell), ping
- **Supervisor**: keeps worker alive, auto-updates from git, runs migrations

## Architecture (target)

```
┌─────────────────────────────────────────────────┐
│  Queue Server (DO)                               │
│  server.py :9999                                 │
│  jobs.db                                         │
│  ├─ jobs (+ target, priority, attempts columns)  │
│  ├─ workers (+ db_bytes, capacity_status, status)│
│  ├─ user_affinity (user_id → worker)             │
│  └─ fan_out_queries                              │
│  watchdog task (async, detects dead workers)      │
└──────┬───────┬───────┬───────────────────────────┘
       │       │       │
       ▼       ▼       ▼
  Worker A  Worker B  Worker C
  /users/   /users/   /users/
   u1.db     u4.db     u7.db
   u2.db     u5.db     u8.db
   u3.db     u6.db     u9.db

  collector.py ──────► archive.db (consolidated)
  migrator.py  ──────► moves users between workers
```

## 7 Strategies

| # | Strategy | What it solves |
|---|----------|----------------|
| 01 | User-Worker Affinity | Route learner data to correct worker |
| 02 | Backpressure & Migration | Handle full disks, rebalance users |
| 03 | Offline Collector & Merge | Archive data for analytics/backup |
| 04 | Worker Health Monitoring | Detect dead workers, recover stuck jobs |
| 05 | Per-User Database Files | Isolate users, simplify migration |
| 06 | Fan-Out Queries | Cross-worker analytics |
| 07 | Priority & Retry | Job ordering, automatic failure recovery |

## Dependency Graph

```
04 Worker Health ──────────────────────┐
07 Priority & Retry ───────────────────┤ (no deps, implement first)
                                       │
01 User-Worker Affinity ◄──────────────┘
       │
       ├──► 05 Per-User Databases
       │         │
       │         ├──► 02 Backpressure & Migration
       │         │
       ├─────────┼──► 03 Offline Collector
       │         │
       └────04───┼──► 06 Fan-Out Queries
                 │
```

## Implementation Order

```
Phase 1 — Foundation (no dependencies):
  04-worker-health.md      server.py only, asyncio watchdog
  07-priority-retry.md     server.py + client.py, column additions

Phase 2 — Core routing:
  01-user-worker-affinity.md   user_affinity table, target on jobs, poll filter

Phase 3 — DB model (decide BEFORE Phase 4):
  05-per-user-databases.md   one .db per user on worker filesystem

Phase 4 — Data management:
  02-backpressure-migration.md   new file migrator.py, worker job handlers
  03-offline-collector.md        new file collector.py

Phase 5 — Analytics:
  06-fan-out-queries.md   fan_out op, result merging
```

## Files Changed Across All Strategies

| File | Strategies | Nature |
|------|-----------|--------|
| `server.py` | 01, 02, 04, 06, 07 | New ops, modified poll/submit/ack, watchdog |
| `worker.py` | 02, 05 | New job handlers, stats reporting, per-user DB |
| `client.py` | 01, 02, 03, 06, 07 | New convenience functions |
| `migrator.py` (new) | 02 | User migration orchestrator (~100 lines) |
| `collector.py` (new) | 03 | Periodic archive collection (~120 lines) |
| `migrate.sh` | 05 | Iterate per-user DB files for schema changes |
| `infrastructure.sh` | 05 | Create users/ directory |

## New Server Ops (all strategies)

| Op | Strategy | Purpose |
|----|----------|---------|
| `affinity` | 01 | View user-to-worker mapping |
| `set_affinity_status` | 02 | Freeze/unfreeze user during migration |
| `set_affinity` | 02 | Reassign user to different worker |
| `health` | 04 | System health summary |
| `fan_out` | 06 | Submit query to all workers |
| `fan_out_status` | 06 | Check/merge fan-out results |

## New Worker Job Types (all strategies)

| Job Type | Strategy | Purpose |
|----------|----------|---------|
| `dump_user` | 02 | Export user's .db file (base64) |
| `import_user` | 02 | Write user's .db file on new worker |
| `prune_user` | 02 | Delete user's .db file from old worker |
| `init_user_db` | 05 | Create new per-user DB with schema |

## Learning App Data (from Kotlin app)

6 synced tables that workers will store per-user:

| Table | Key columns |
|-------|-------------|
| `session_events` | eventType, timestamp, durationMs, chapterName, pageId |
| `annotation_records` | imageId, boxIndex, boxX/Y/W/H, label, regionType |
| `chat_messages` | sender, text, timestamp |
| `page_interactions` | interactionType, chapterName, pageId, normalizedX/Y |
| `app_launch_records` | packageName, currentChapter, currentPageId |
| `settings_changes` | setting, oldValue, newValue |

User ID comes at the sync payload root level, NOT per-record.
