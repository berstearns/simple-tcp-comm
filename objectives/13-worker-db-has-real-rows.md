# 13 — Worker DB Has Real Rows (Correct comic_id, No Collisions)

**Owner:** implementer
**Depends on:** 12

## Success criterion

After the worker ingests the auto-synced payload, the timestamped worker DB has:
- `session_events` rows with real `event_type` values (APP_START, PAGE_ENTER, etc.)
- `comic_id` values matching the comics the user actually browsed (NOT `_no_comic_`, NOT fake test IDs)
- `chapters` table has correct `(comic_id, chapter_name)` composite keys
- `ingest_batches` has at least 1 row with `schema_version >= 4`
- `device_id = 'sdk_gphone64_x86_64'` on all rows (proving it came from the emulator)

## How to verify

```bash
TS=YYYYMMDD_HHMMSS  # replace with actual timestamp from setup_e2e_local.sh

sqlite3 /home/b/simple-tcp-comm-worker-deploy/dbs/${TS}/app7.db <<'SQL'
.mode column
.headers on

SELECT '=== row counts ===' AS '';
SELECT 'session_events'     AS tbl, COUNT(*) AS n FROM session_events   UNION ALL
SELECT 'page_interactions',         COUNT(*)      FROM page_interactions UNION ALL
SELECT 'settings_changes',          COUNT(*)      FROM settings_changes  UNION ALL
SELECT 'comics',                    COUNT(*)      FROM comics            UNION ALL
SELECT 'chapters',                  COUNT(*)      FROM chapters          UNION ALL
SELECT 'ingest_batches',            COUNT(*)      FROM ingest_batches;

SELECT '=== comics ===' AS '';
SELECT * FROM comics;

SELECT '=== chapters ===' AS '';
SELECT comic_id, chapter_name FROM chapters;

SELECT '=== device check ===' AS '';
SELECT DISTINCT device_id FROM session_events;

SELECT '=== schema version ===' AS '';
SELECT schema_version, device_id, mode FROM ingest_batches;
SQL
```

## Pass criteria

- `session_events > 0`, `comics > 0`, `chapters > 0`
- `device_id = 'sdk_gphone64_x86_64'` (emulator, not a fake device)
- `schema_version >= 4` in `ingest_batches`
- `comic_id` values are real asset IDs (e.g., `batch-01-hq-tokens`)
- No rows with `comic_id = 'one_piece'` or `'naruto'` (those are test-only IDs)

## Fail criteria

- Zero rows → worker didn't ingest (check worker pane for errors)
- `device_id` is a Python test string → data came from a fake payload
- `comic_id = '_no_comic_'` on fresh rows → producer-side comicId population broken

## Current status

- [ ] Not started
- [ ] In progress
- [ ] Verified

## Evidence

(fill in after worker ingests real data)
