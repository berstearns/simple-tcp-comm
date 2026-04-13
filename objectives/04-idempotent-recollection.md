# 04 — Idempotent Re-collection (INSERT OR IGNORE Safety Net)

**Owner:** implementer
**Depends on:** 03

## Success criterion

Even when watermarks are **manually deleted** from `collection_log` (simulating data loss or a "start from scratch" scenario), re-collecting the same data produces **zero new rows** because `INSERT OR IGNORE` on the UNIQUE constraints catches every duplicate.

This is the safety net: watermarks are an optimization (avoid re-scanning already-collected data), but idempotency does NOT depend on them. The UNIQUE constraints are the true dedup mechanism.

### UNIQUE constraints per table type

| Table type | Archive UNIQUE constraint |
|---|---|
| Event/session (11 tables) | `(_source_worker, device_id, local_id)` |
| Catalog: comics | `(_source_worker, comic_id)` |
| Catalog: chapters | `(_source_worker, comic_id, chapter_name)` |
| Catalog: pages | `(_source_worker, comic_id, page_id)` |
| Catalog: images | `(_source_worker, image_id)` |
| `ingest_batches` | `(_source_worker, id)` |
| `region_translations` | `(_source_worker, image_id, bubble_index)` |

## How to verify

```bash
rm -f /tmp/test-archive.db

# Run 1: populate
ARCHIVE_DB=/tmp/test-archive.db python3 /home/b/simple-tcp-comm/collector.py collect \
  --direct /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db \
  --worker-name test-worker

# Capture row counts after first run
echo "=== After run 1 ==="
for t in comics ingest_batches app_sessions comic_sessions; do
  n=$(sqlite3 /tmp/test-archive.db "SELECT COUNT(*) FROM $t;")
  echo "  $t: $n"
done

# Wipe ALL watermarks
sqlite3 /tmp/test-archive.db "DELETE FROM collection_log;"
echo "=== Watermarks wiped ==="

# Run 2: re-collect with no watermarks (full re-scan)
ARCHIVE_DB=/tmp/test-archive.db python3 /home/b/simple-tcp-comm/collector.py collect \
  --direct /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db \
  --worker-name test-worker

# Verify row counts are UNCHANGED
echo "=== After run 2 (post-wipe) ==="
for t in comics ingest_batches app_sessions comic_sessions; do
  n=$(sqlite3 /tmp/test-archive.db "SELECT COUNT(*) FROM $t;")
  echo "  $t: $n"
done

# Check collection_log shows rows_skipped > 0 for tables with data
sqlite3 /tmp/test-archive.db \
  "SELECT table_name, rows_collected, rows_skipped FROM collection_log WHERE rows_skipped > 0;"
```

## Expected output

Row counts identical before and after watermark wipe + re-collection:
```
=== After run 1 ===
  comics: 2
  ingest_batches: 2
  app_sessions: 2
  comic_sessions: 2
=== Watermarks wiped ===
=== After run 2 (post-wipe) ===
  comics: 2
  ingest_batches: 2
  app_sessions: 2
  comic_sessions: 2
```

Second run's `collection_log` shows `rows_collected=0, rows_skipped=2` for every table with data:
```
comics|0|2
ingest_batches|0|2
app_sessions|0|2
comic_sessions|0|2
```

## Pass criteria

- Row counts unchanged between run 1 and post-wipe run 2
- No UNIQUE constraint violation errors (INSERT OR IGNORE silently skips)
- `rows_skipped` values in `collection_log` match the number of rows that were already in the archive
- Script does not crash

## Fail criteria

- Row counts double (INSERT OR IGNORE not working — UNIQUE constraint missing or wrong)
- UNIQUE constraint error crashes the script (should never happen with INSERT OR IGNORE)
- `rows_skipped = 0` when rows should have been skipped (UNIQUE constraint not catching dupes)

## Current status

- [ ] Not started
- [ ] In progress
- [x] Verified

## Evidence

Verified 2026-04-12.

After wiping `collection_log` and re-collecting (run `e1cabfb8`): `0 rows collected, 8 skipped`. All 4 non-empty tables reported `0 new, 2 skipped`. Row counts unchanged: `comics=2, ingest_batches=2, app_sessions=2, comic_sessions=2`. INSERT OR IGNORE on UNIQUE constraints caught every duplicate without error.
