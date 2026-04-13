# 02 — Direct Mode Collects All 16 Data Tables

**Owner:** implementer
**Depends on:** 01

## Success criterion

After running `collector.py collect --direct` against the worker DB at `/home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db`, the archive contains the **exact same row count** as the worker for every table. The `_source_worker` value on all archived rows matches the `--worker-name` argument.

The collector must handle all 16 data tables, including:
- Catalog tables with TEXT PKs (no integer autoincrement)
- `region_translations` with `id TEXT PRIMARY KEY` (not integer)
- `ingest_batches` with `id INTEGER PRIMARY KEY AUTOINCREMENT`
- All event/session tables with `(device_id, local_id)` UNIQUE constraints

## How to verify

```bash
rm -f /tmp/test-archive.db
ARCHIVE_DB=/tmp/test-archive.db python3 /home/b/simple-tcp-comm/collector.py collect \
  --direct /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db \
  --worker-name bernardo-pc-app7-hierarchy-verify

# Compare row counts for every table
for t in comics chapters pages images ingest_batches session_events annotation_records \
         chat_messages page_interactions app_launch_records settings_changes \
         region_translations app_sessions comic_sessions chapter_sessions page_sessions; do
  w=$(sqlite3 /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db "SELECT COUNT(*) FROM $t;")
  a=$(sqlite3 /tmp/test-archive.db "SELECT COUNT(*) FROM $t;")
  echo "$t: worker=$w archive=$a match=$([ "$w" = "$a" ] && echo YES || echo NO)"
done

# Verify _source_worker is correct on all non-empty tables
sqlite3 /tmp/test-archive.db "SELECT _source_worker, COUNT(*) FROM comics GROUP BY _source_worker;"
sqlite3 /tmp/test-archive.db "SELECT _source_worker, COUNT(*) FROM ingest_batches GROUP BY _source_worker;"
sqlite3 /tmp/test-archive.db "SELECT _source_worker, COUNT(*) FROM app_sessions GROUP BY _source_worker;"
sqlite3 /tmp/test-archive.db "SELECT _source_worker, COUNT(*) FROM comic_sessions GROUP BY _source_worker;"
```

## Expected output

All 16 lines show `match=YES`. All `_source_worker` queries return `bernardo-pc-app7-hierarchy-verify|<count>`.

Based on current worker DB state (as of 2026-04-12):
```
comics: worker=2 archive=2 match=YES
chapters: worker=0 archive=0 match=YES
pages: worker=0 archive=0 match=YES
images: worker=0 archive=0 match=YES
ingest_batches: worker=2 archive=2 match=YES
session_events: worker=0 archive=0 match=YES
annotation_records: worker=0 archive=0 match=YES
chat_messages: worker=0 archive=0 match=YES
page_interactions: worker=0 archive=0 match=YES
app_launch_records: worker=0 archive=0 match=YES
settings_changes: worker=0 archive=0 match=YES
region_translations: worker=0 archive=0 match=YES
app_sessions: worker=2 archive=2 match=YES
comic_sessions: worker=2 archive=2 match=YES
chapter_sessions: worker=0 archive=0 match=YES
page_sessions: worker=0 archive=0 match=YES
```

## Pass criteria

- Every table shows `match=YES`
- `_source_worker` is `bernardo-pc-app7-hierarchy-verify` on all archived rows
- No crashes, no error output from the collector
- Collector output shows non-zero `rows collected` for tables with data

## Fail criteria

- Any table shows `match=NO` (row count mismatch)
- `_source_worker` is NULL or empty on any row
- Collector crashes mid-collection (partial archive)
- A table in the worker is silently skipped (not listed in collector output)

## Current status

- [ ] Not started
- [ ] In progress
- [x] Verified

## Evidence

Verified 2026-04-12. `OVERALL: PASS (16/16 tables match)`, exit=0.

All 16 tables `match=YES`. Non-empty tables: `comics=2`, `ingest_batches=2`, `app_sessions=2`, `comic_sessions=2`. All `_source_worker=bernardo-pc-app7-hierarchy-verify`.
