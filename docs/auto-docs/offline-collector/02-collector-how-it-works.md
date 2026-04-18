# How the Collector Works

> From conversation: explaining the current collector implementation.

## Overview

The collector (`/home/b/simple-tcp-comm/collector.py`) copies rows from a worker's sqlite DB into an archive DB, with deduplication.

```
Worker DB (app7.db)          collector.py            Archive DB (archive.db)
┌──────────────────┐                                ┌──────────────────────┐
│ session_events   │──── SELECT * WHERE id > wm ──►│ session_events       │
│ page_interactions│     (incremental)              │ + _source_worker col │
│ annotation_records│                               │ + _archive_id PK     │
│ comics, chapters │──── SELECT * (full scan) ────►│ UNIQUE constraint    │
│ ... (16 tables)  │     INSERT OR IGNORE           │ catches dupes        │
└──────────────────┘                                ├──────────────────────┤
                                                    │ collection_log       │
                                                    │ (watermarks per run) │
                                                    └──────────────────────┘
```

## Two collection strategies by table type

**Tables with `id INTEGER PRIMARY KEY`** (11 tables: 6 event + 4 session + ingest_batches):
- First run: `SELECT * FROM session_events WHERE id > 0 ORDER BY id`
- Stores `max(id)` as watermark in `collection_log`
- Next run: `SELECT * FROM session_events WHERE id > 32 ORDER BY id` — only gets new rows
- If nothing new, 0 rows fetched, fast no-op

**Tables without integer PK** (4 catalog + region_translations):
- Always `SELECT *` (full scan, they're small)
- `INSERT OR IGNORE` on the UNIQUE constraint skips existing rows
- Shows as `0 new, N skipped` on repeat runs

## Deduplication (two layers)

1. **Watermarks** (optimization) — skip rows already collected by querying `WHERE id > last_max_rowid`
2. **UNIQUE constraints** (safety net) — even if watermarks are lost, `INSERT OR IGNORE` on `(_source_worker, device_id, local_id)` prevents duplicates

## Two modes

**`--direct`** (primary): opens the worker DB file directly via sqlite3. Fast, same-machine only.

**`--queue`**: submits `SELECT *` as a `query` job to the DO queue, worker executes it and returns rows in the job result. Works remotely across NAT, but slower (one TCP round-trip per table).

## CLI

```bash
collector.py collect --direct /path/to/worker.db --worker-name NAME
collector.py collect --queue --worker-name NAME --db app7
collector.py verify  --direct /path/to/worker.db --worker-name NAME
collector.py status
collector.py prune --days 90
```

## Archive schema

Mirrors all 16 worker tables, with:
- `_archive_id INTEGER PRIMARY KEY` (replaces original PK)
- `_source_worker TEXT NOT NULL` (which worker the data came from)
- FK constraints dropped (archive is read-only analytics)

Schema: `/home/b/simple-tcp-comm/archive_schema.sql`
