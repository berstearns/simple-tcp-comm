# 06 — Status and Prune Subcommands

**Owner:** implementer
**Depends on:** 02

## Success criterion

### Status

`python3 collector.py status` prints a human-readable summary of the archive:
- Archive file path
- Last collection timestamp and run_id
- Per-worker breakdown: table name, rows collected, rows skipped, watermark
- Archive totals: per-table row counts for non-empty tables

### Prune

`python3 collector.py prune --days N` deletes rows from the archive where the table's timestamp column is older than N days ago. Specifically:
- Event tables use `timestamp` column
- Session tables use `start_ts` (app/comic/chapter sessions) or `enter_ts` (page sessions)
- Catalog tables (`comics`, `chapters`, `pages`, `images`), `ingest_batches`, and `region_translations` are **never pruned** (they have no timestamp column or `ts_col=None` in the registry)
- `collection_log` is never pruned

## How to verify

```bash
# Setup: create a populated archive
rm -f /tmp/test-archive.db
ARCHIVE_DB=/tmp/test-archive.db python3 /home/b/simple-tcp-comm/collector.py collect \
  --direct /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db \
  --worker-name test-worker

# 1. Test status output
ARCHIVE_DB=/tmp/test-archive.db python3 /home/b/simple-tcp-comm/collector.py status

# 2. Record pre-prune counts
echo "=== Pre-prune ==="
sqlite3 /tmp/test-archive.db "SELECT COUNT(*) AS comics FROM comics;"
sqlite3 /tmp/test-archive.db "SELECT COUNT(*) AS app_sessions FROM app_sessions;"
sqlite3 /tmp/test-archive.db "SELECT COUNT(*) AS comic_sessions FROM comic_sessions;"
sqlite3 /tmp/test-archive.db "SELECT COUNT(*) AS ingest_batches FROM ingest_batches;"

# 3. Prune everything (--days 0 = older than right now = everything with a timestamp)
ARCHIVE_DB=/tmp/test-archive.db python3 /home/b/simple-tcp-comm/collector.py prune --days 0

# 4. Verify post-prune state
echo "=== Post-prune ==="
sqlite3 /tmp/test-archive.db "SELECT COUNT(*) AS comics FROM comics;"
sqlite3 /tmp/test-archive.db "SELECT COUNT(*) AS app_sessions FROM app_sessions;"
sqlite3 /tmp/test-archive.db "SELECT COUNT(*) AS comic_sessions FROM comic_sessions;"
sqlite3 /tmp/test-archive.db "SELECT COUNT(*) AS ingest_batches FROM ingest_batches;"

# 5. Test status on empty archive (no crash)
rm -f /tmp/empty-archive.db
ARCHIVE_DB=/tmp/empty-archive.db python3 /home/b/simple-tcp-comm/collector.py status
```

## Expected output

### Status output
```
Archive: /tmp/test-archive.db
Last collection: <ISO timestamp>
Run: <8-char UUID>

Worker: test-worker
  app_sessions                   2 rows  wm=2
  comic_sessions                 2 rows  wm=2
  comics                         2 rows (2 skipped)
  ingest_batches                 2 rows  wm=2
  ... (remaining tables show 0 rows)

Archive totals:
  comics                           2
  ingest_batches                   2
  app_sessions                     2
  comic_sessions                   2
```

### Pre-prune
```
comics = 2
app_sessions = 2
comic_sessions = 2
ingest_batches = 2
```

### Prune output
```
Pruning rows older than 0 days (cutoff timestamp: ...)
  app_sessions               2 rows pruned
  comic_sessions             2 rows pruned

Total: 4 rows pruned
```

### Post-prune
```
comics = 2            ← NOT pruned (catalog, no ts_col)
app_sessions = 0      ← pruned (has start_ts)
comic_sessions = 0    ← pruned (has start_ts)
ingest_batches = 2    ← NOT pruned (audit, ts_col=None)
```

### Empty archive status
```
archive not found: /tmp/empty-archive.db
```
(exits 1 — no crash)

## Pass criteria

- `status` prints readable output without crash
- `status` shows correct per-worker per-table breakdown
- `prune --days 0` empties `app_sessions` and `comic_sessions` (which have `start_ts`)
- `prune` does NOT delete from `comics`, `chapters`, `pages`, `images`, `ingest_batches`, `region_translations`
- `status` on missing archive prints error and exits cleanly

## Fail criteria

- `status` crashes
- `prune` deletes catalog rows or `ingest_batches`
- `prune` crashes on tables with no timestamp column
- Wrong timestamp column used for prune (e.g., using `timestamp` on `page_sessions` which has `enter_ts`)

## Current status

- [ ] Not started
- [ ] In progress
- [x] Verified

## Evidence

Verified 2026-04-12.

**Status** printed readable output: archive path, last collection run_id, per-worker per-table breakdown with row counts, watermarks, and archive totals.

**Prune `--days 0`** correctly deleted 4 rows: `app_sessions: 2 rows pruned`, `comic_sessions: 2 rows pruned`. Post-prune: `comics=2` (untouched, catalog), `ingest_batches=2` (untouched, no ts_col), `app_sessions=0` (pruned), `comic_sessions=0` (pruned).

**Status on missing archive** printed `archive not found:` and exited 1 (no crash).
