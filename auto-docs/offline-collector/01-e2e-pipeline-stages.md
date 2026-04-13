# E2E Pipeline — 7 Verification Stages

> From conversation: mapping the full data flow from Android app to archive DB.

## Pipeline

```
Stage 1          Stage 2              Stage 3           Stage 4
App logs      →  UnifiedPayload    →  DO Queue        →  Worker polls
(Room DB on      built + serialized   server holds        job from queue
 emulator)       by TcpQueueSyncApi   the job             every 2s

Stage 5          Stage 6              Stage 7
Worker saves  →  Round-trip        →  Offline collector
in own sqlite    comparator           merges worker DBs
DB               confirms match       into global archive
```

## Verification checkpoints

| # | Stage | What to check | Key tool |
|---|-------|--------------|----------|
| 1 | App logs to Room | `synced=0` rows in emulator sqlite, `comicId` populated | `adb exec-out run-as pl.czak.imageviewer.app7 sqlite3 databases/learner_data.db` |
| 2 | Payload submitted | `submit ok id=` in logcat | `adb logcat -d \| grep 'submit ok'` |
| 3 | Job on queue | Job visible via client.py | `python3 client.py ls` |
| 4 | Worker picks up | `accepted: True` in job status | `python3 client.py status <N>` |
| 5 | Worker DB populated | Row counts, collision-freedom check | `sqlite3 /path/to/worker/app7.db` |
| 6 | Round-trip match | Comparator reports PASS | `python3 scripts/verify-sync-roundtrip.py --worker-db ...` |
| 7 | Offline collector | Merges worker DBs into archive.db | `python3 collector.py collect --direct ...` |

## Full objective reference

Detailed verification commands per stage: `app7-explicit-db-hierarchy-bug-fixes_20260410_161800/objectives/30-e2e-pipeline-verification.md`
