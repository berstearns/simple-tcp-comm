# 01 — Archive Schema Creates Cleanly

**Owner:** implementer
**Depends on:** none

## Success criterion

Running `collector.py collect --direct` against any worker DB (even an empty one) creates an archive DB with all 17 tables:

- 4 catalog: `comics`, `chapters`, `pages`, `images`
- 1 audit: `ingest_batches`
- 7 event: `session_events`, `annotation_records`, `chat_messages`, `page_interactions`, `app_launch_records`, `settings_changes`, `region_translations`
- 4 session hierarchy: `app_sessions`, `comic_sessions`, `chapter_sessions`, `page_sessions`
- 1 collection audit: `collection_log`

Every data table (all except `collection_log`) has a `_source_worker TEXT NOT NULL` column. Every data table has an `_archive_id INTEGER PRIMARY KEY AUTOINCREMENT` column replacing the original PK.

The schema is loaded from `/home/b/simple-tcp-comm/archive_schema.sql`.

## How to verify

```bash
rm -f /tmp/test-archive.db
ARCHIVE_DB=/tmp/test-archive.db python3 /home/b/simple-tcp-comm/collector.py collect \
  --direct /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db \
  --worker-name test

# 1. Count tables (expect 17 + sqlite_sequence = 18 in sqlite_master)
sqlite3 /tmp/test-archive.db "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"

# 2. Check _source_worker exists on data tables
for t in comics chapters pages images ingest_batches session_events annotation_records \
         chat_messages page_interactions app_launch_records settings_changes \
         region_translations app_sessions comic_sessions chapter_sessions page_sessions; do
  has=$(sqlite3 /tmp/test-archive.db "PRAGMA table_info($t);" | grep "_source_worker" | wc -l)
  echo "$t: _source_worker=$([ $has -gt 0 ] && echo YES || echo NO)"
done

# 3. Check _archive_id exists on data tables
for t in comics session_events app_sessions; do
  has=$(sqlite3 /tmp/test-archive.db "PRAGMA table_info($t);" | grep "_archive_id" | wc -l)
  echo "$t: _archive_id=$([ $has -gt 0 ] && echo YES || echo NO)"
done

# 4. Check collection_log was populated
sqlite3 /tmp/test-archive.db "SELECT COUNT(*) AS log_entries FROM collection_log;"
```

## Expected output

Table list (17 tables):
```
annotation_records
app_launch_records
app_sessions
chapter_sessions
chapters
chat_messages
collection_log
comic_sessions
comics
images
ingest_batches
page_interactions
page_sessions
pages
region_translations
session_events
settings_changes
```

All `_source_worker=YES`. All `_archive_id=YES`. `log_entries >= 16` (one per table collected).

## Pass criteria

- All 17 tables exist in the archive
- Every data table has `_source_worker TEXT NOT NULL`
- Every data table has `_archive_id INTEGER PRIMARY KEY AUTOINCREMENT`
- `collection_log` has at least 16 rows (one per table)
- Script does not crash

## Fail criteria

- Any table missing from the archive
- `_source_worker` column absent on any data table
- Script crashes during schema creation (missing `archive_schema.sql`, SQL syntax error)
- `collection_log` empty

## Current status

- [ ] Not started
- [ ] In progress
- [x] Verified

## Evidence

Verified 2026-04-12.

17 tables created (+ `sqlite_sequence`). All 16 data tables have `_source_worker=YES`. `collection_log` has 16 entries (one per table).

```
annotation_records, app_launch_records, app_sessions, chapter_sessions, chapters,
chat_messages, collection_log, comic_sessions, comics, images, ingest_batches,
page_interactions, page_sessions, pages, region_translations, session_events,
settings_changes
```

All 16 data tables confirmed `_source_worker=YES`. `log_entries=16`.
