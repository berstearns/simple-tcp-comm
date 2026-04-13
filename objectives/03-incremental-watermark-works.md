# 03 — Incremental Watermark Works

**Owner:** implementer
**Depends on:** 02

## Success criterion

Running the collector **twice in a row** against the same worker DB produces:
- First run: N rows collected (matching worker data)
- Second run: **0 rows collected** for all tables that use `id`-based watermarking (event tables, session tables, `ingest_batches`)
- Second run: **0 new, N skipped** for catalog tables (which do full-scan with INSERT OR IGNORE)

The `collection_log` table shows two distinct `run_id` values. The second run's entries all have `rows_collected=0`. No row counts in the data tables change between runs.

### How watermarking works

Tables with `id INTEGER PRIMARY KEY AUTOINCREMENT` (11 tables: 6 event + 4 session + `ingest_batches`):
- After first collection, `collection_log.max_rowid` stores `max(id)` from the source
- Second run queries `WHERE id > max_rowid` — returns 0 rows since nothing changed
- Only new rows (with higher `id`) would be collected

Tables without integer PK (4 catalog + `region_translations`):
- Always do `SELECT *` (no watermark)
- `INSERT OR IGNORE` on the UNIQUE constraint prevents duplicates
- These show `rows_skipped=N` on the second run (not `rows_collected=0`)

## How to verify

```bash
rm -f /tmp/test-archive.db

# Run 1
ARCHIVE_DB=/tmp/test-archive.db python3 /home/b/simple-tcp-comm/collector.py collect \
  --direct /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db \
  --worker-name test-worker

# Run 2 (same data, should be incremental no-op)
ARCHIVE_DB=/tmp/test-archive.db python3 /home/b/simple-tcp-comm/collector.py collect \
  --direct /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db \
  --worker-name test-worker

# Check collection_log: two run_ids, second run all zeros
sqlite3 /tmp/test-archive.db <<'SQL'
.mode column
.headers on
SELECT run_id, table_name, rows_collected, rows_skipped, max_rowid
FROM collection_log
ORDER BY id;
SQL

# Verify row counts did not inflate
sqlite3 /tmp/test-archive.db "SELECT COUNT(*) AS comics_count FROM comics;"
sqlite3 /tmp/test-archive.db "SELECT COUNT(*) AS app_sessions_count FROM app_sessions;"
sqlite3 /tmp/test-archive.db "SELECT COUNT(*) AS ingest_batches_count FROM ingest_batches;"

# Count distinct run_ids
sqlite3 /tmp/test-archive.db "SELECT COUNT(DISTINCT run_id) AS num_runs FROM collection_log;"
```

## Expected output

Two distinct `run_id` values in `collection_log`. Second run shows:
- `ingest_batches`: `rows_collected=0` (watermarked, no new rows)
- `app_sessions`: `rows_collected=0` (watermarked)
- `comic_sessions`: `rows_collected=0` (watermarked)
- `comics`: `rows_collected=0, rows_skipped=2` (full-scan, INSERT OR IGNORE caught dupes)

Row counts remain unchanged: `comics=2`, `app_sessions=2`, `ingest_batches=2`.

## Pass criteria

- Two distinct `run_id` values in `collection_log`
- Second run's watermarked tables: `rows_collected=0`
- Second run's catalog tables: `rows_collected=0, rows_skipped=N`
- No row count inflation in any data table
- `num_runs = 2`

## Fail criteria

- Only one `run_id` (second run didn't log)
- Second run's watermarked tables show `rows_collected > 0` (watermark not applied)
- Row counts doubled (watermark broken, data re-inserted)
- Second run crashes

## Current status

- [ ] Not started
- [ ] In progress
- [x] Verified

## Evidence

Verified 2026-04-12.

Run 1 (`49ba096b`): 8 rows collected, 0 skipped.
Run 2 (`7aa283ea`): 0 rows collected, 2 skipped (catalog full-scan caught by INSERT OR IGNORE).
`num_runs=2`. Row counts unchanged: `comics=2, ingest_batches=2, app_sessions=2, comic_sessions=2`.

Watermarked tables (ingest_batches, app_sessions, comic_sessions) showed `0 new` on second run — `WHERE id > max_rowid` returned 0 rows. Catalog tables (comics) showed `0 new, 2 skipped` — full scan + INSERT OR IGNORE.
