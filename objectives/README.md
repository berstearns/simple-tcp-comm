# Objectives — Offline Collector

This folder tracks the success checklist for `collector.py` — the offline DB collector that merges worker sqlite DBs into a consolidated archive for analytics, backup, and cross-worker queries.

## What's being verified

A single outcome: data flows from worker instance DBs into a global archive DB with full idempotency, incremental watermarks, and row-count verification.

```
Worker DB (app7-hierarchy-verify.db)
    ↓  collector.py --direct (or --queue)
Archive DB (archive.db)
    ↓  collector.py verify
Row-count match confirmed
```

## Ordering

```
00  ── collector main goal (composite)
│
├── 01 (archive schema creates cleanly — 17 tables, _source_worker on all)
│      │
│      └── 02 (direct mode collects all 16 data tables)
│             │
│             └── 03 (incremental watermark — second run inserts 0 new rows)
│                    │
│                    └── 04 (idempotent re-collection — INSERT OR IGNORE catches dupes after watermark wipe)
│                           │
│                           └── 05 (queue mode collects — same results as direct, via TCP queue)
│                                  │
│                                  └── 06 (status + prune subcommands)
│                                         │
│                                         └── 07 (verify subcommand — row counts match, exit 0)
```

## Part 2 — Real App E2E (objectives 10-14)

Proves the full pipeline using the **real Android app** — no fake Python payloads. The user opens the app, taps around, auto-sync fires, data flows through the DO queue to a fresh local worker, and the collector archives it.

```
10  ── real app E2E main goal (composite)
│
├── 11 (emulator Room DB has rows from real user actions)
│      └── 12 (auto-sync sends through DO queue — Kotlin TCP, not Python)
│             └── 13 (worker DB has real rows — correct comic_id, emulator device_id)
│                    └── 14 (collector archive matches worker — OVERALL: PASS)
```

Setup: `/home/b/simple-tcp-comm/setup_e2e_local.sh`
Instructions: `/home/b/simple-tcp-comm/deploy_e2e_local.md`

## Key files

| File | Role |
|------|------|
| `/home/b/simple-tcp-comm/collector.py` | Main collector script |
| `/home/b/simple-tcp-comm/archive_schema.sql` | Archive DDL (standalone reference) |
| `/home/b/simple-tcp-comm/client.py` | TCP client (imported by queue mode) |
| `/home/b/simple-tcp-comm/setup_e2e_local.sh` | One-command E2E setup (tmux + worker + collector) |
| `/home/b/simple-tcp-comm/deploy_e2e_local.md` | Detailed deployment instructions |

## How to use this folder

Same convention as the app7 feature folder objectives:

1. Each objective file has a `## Current status` checklist.
2. Fill in the `## Evidence` section with actual command output when verifying.
3. `grep -l "\[x\] Verified" *.md` for a quick pass-count.
