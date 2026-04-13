# 07 — Verify Subcommand: Row Counts Match

**Owner:** implementer
**Depends on:** 02

## Success criterion

`python3 collector.py verify --direct PATH --worker-name NAME` compares the archive against the worker DB and:
- Prints per-table: `worker=N archive=N OK` or `MISMATCH`
- Prints `OVERALL: PASS (M/M tables match)` when all match
- Exits with code 0 on PASS, code 1 on FAIL
- Filters archive rows by `_source_worker=NAME` (so multi-worker archives report correctly per worker)
- Skips tables that don't exist in the worker (prints `SKIP`)

## How to verify

```bash
# 1. Create a matching archive
rm -f /tmp/test-archive.db
ARCHIVE_DB=/tmp/test-archive.db python3 /home/b/simple-tcp-comm/collector.py collect \
  --direct /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db \
  --worker-name test-worker

# 2. Verify (should PASS)
ARCHIVE_DB=/tmp/test-archive.db python3 /home/b/simple-tcp-comm/collector.py verify \
  --direct /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db \
  --worker-name test-worker
echo "exit=$?"

# 3. Inject a mismatch to test FAIL case
sqlite3 /tmp/test-archive.db "DELETE FROM comics WHERE _archive_id = (SELECT MAX(_archive_id) FROM comics);"

# 4. Verify again (should FAIL on comics)
ARCHIVE_DB=/tmp/test-archive.db python3 /home/b/simple-tcp-comm/collector.py verify \
  --direct /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db \
  --worker-name test-worker
echo "exit=$?"
```

## Expected output

### PASS case
```
Verify: archive vs worker (direct)
  archive: /tmp/test-archive.db
  worker:  /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db
  name:    test-worker

  comics                     worker=2        archive=2        OK
  chapters                   worker=0        archive=0        OK
  pages                      worker=0        archive=0        OK
  images                     worker=0        archive=0        OK
  ingest_batches             worker=2        archive=2        OK
  session_events             worker=0        archive=0        OK
  annotation_records         worker=0        archive=0        OK
  chat_messages              worker=0        archive=0        OK
  page_interactions          worker=0        archive=0        OK
  app_launch_records         worker=0        archive=0        OK
  settings_changes           worker=0        archive=0        OK
  region_translations        worker=0        archive=0        OK
  app_sessions               worker=2        archive=2        OK
  comic_sessions             worker=2        archive=2        OK
  chapter_sessions           worker=0        archive=0        OK
  page_sessions              worker=0        archive=0        OK

OVERALL: PASS (16/16 tables match)
exit=0
```

### FAIL case (after deleting 1 comic row from archive)
```
  comics                     worker=2        archive=1        MISMATCH
  ...
OVERALL: FAIL (15/16 tables match)
exit=1
```

## Pass criteria

- PASS case: all 16 tables `OK`, exit code 0
- FAIL case: `comics` shows `MISMATCH`, exit code 1
- Output includes all 16 data tables
- `--worker-name` correctly filters archive rows (only counts rows with matching `_source_worker`)

## Fail criteria

- Exit code 0 when there's a mismatch
- Wrong row counts (archive counts all workers instead of filtering by `--worker-name`)
- Missing tables in output
- Crashes on empty worker DB or empty archive

## Current status

- [ ] Not started
- [ ] In progress
- [x] Verified

## Evidence

Verified 2026-04-12.

**PASS case:** `OVERALL: PASS (16/16 tables match)`, exit=0. All tables `OK`.

**FAIL case** (after deleting 1 comic row from archive): `comics worker=2 archive=1 MISMATCH`. `OVERALL: FAIL (15/16 tables match)`, exit=1. Correctly detected the injected mismatch.
