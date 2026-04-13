# 14 — Collector Archive Matches Worker DB (Real Data, OVERALL: PASS)

**Owner:** implementer
**Depends on:** 13

## Success criterion

The collector's 60s loop (running in the bottom pane of `app7-e2e`) has:
1. Collected all rows from the worker DB into the archive
2. `verify` reports `OVERALL: PASS (16/16 tables match)`
3. The archive's `_source_worker` matches the `e2e-*` worker name
4. The archive's `collection_log` shows at least 1 run with `rows_collected > 0`

This is the final stage: data that started as a user tap in the Android app is now in a consolidated archive DB, collected from a worker that ingested it via the DO queue. Every stage used real production code.

## How to verify

```bash
TS=YYYYMMDD_HHMMSS  # replace with actual timestamp

# 1. Check the collector pane output (should show OVERALL: PASS)
# Or run manually:
ARCHIVE_DB=/home/b/simple-tcp-comm-worker-deploy/offline-collected/${TS}/archive.db \
  python3 /home/b/simple-tcp-comm/collector.py verify \
    --direct /home/b/simple-tcp-comm-worker-deploy/dbs/${TS}/app7.db \
    --worker-name e2e-${TS}
echo "exit=$?"

# 2. Check collection log
ARCHIVE_DB=/home/b/simple-tcp-comm-worker-deploy/offline-collected/${TS}/archive.db \
  python3 /home/b/simple-tcp-comm/collector.py status

# 3. Spot check: archive has the same device_id as the emulator
sqlite3 /home/b/simple-tcp-comm-worker-deploy/offline-collected/${TS}/archive.db \
  "SELECT DISTINCT _source_worker, device_id FROM session_events;"
```

## Expected output

```
OVERALL: PASS (16/16 tables match)
exit=0
```

Status shows:
```
Worker: e2e-YYYYMMDD_HHMMSS
  session_events:  N rows
  page_interactions: M rows
  ...
```

Spot check:
```
e2e-YYYYMMDD_HHMMSS|sdk_gphone64_x86_64
```

## Pass criteria

- `OVERALL: PASS (16/16 tables match)`, exit code 0
- `_source_worker` is `e2e-YYYYMMDD_HHMMSS` (matches the run)
- `device_id` is `sdk_gphone64_x86_64` (emulator, not a test device)
- `collection_log` has at least 1 entry with `rows_collected > 0`

## Fail criteria

- `FAIL` on any table → collector bug or race condition
- `_source_worker` is wrong → env file misconfigured
- `device_id` is a fake test ID → data didn't come from the real app
- Archive is empty → collector hasn't run yet (wait for the 60s cycle)

## Current status

- [ ] Not started
- [ ] In progress
- [ ] Verified

## Evidence

(fill in after collector cycle completes with real data)
