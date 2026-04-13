# 12 — Auto-Sync Sends Through DO Queue (Real Kotlin TCP, Not Python)

**Owner:** implementer (watch logcat + worker pane)
**Depends on:** 11

## Success criterion

After auto-sync fires (~60s after app launch with `auto_sync=true`), a real `ingest_unified_payload` job appears on the DO queue server:
- Submitted by the **Kotlin** `TcpQueueSyncApi.upload()`, NOT by a Python script
- `schema_version = 5` (or 4)
- `device_id` matches the emulator (e.g., `sdk_gphone64_x86_64`)
- Worker acks with `accepted: True`

The proof that it came from the app (not Python) is:
1. The `device_id` matches the emulator's `Build.DEVICE`
2. The `app_version` matches the installed APK
3. Logcat shows `AutoSync: triggering SyncService.sync()` followed by `submit ok id=NNNN`
4. The job's `worker.ip` is your IP (the worker polling from your machine)

## How to verify

```bash
# 1. Watch logcat for the sync event
adb logcat -v time -d | grep -E 'AutoSync|submit ok id=' | tail -10

# 2. Get the job ID from logcat
N=$(adb logcat -v time -d | grep 'submit ok id=' | tail -1 | grep -oE 'id=[0-9]+' | cut -d= -f2)
echo "Job ID: $N"

# 3. Inspect the job on the DO queue
python3 /home/b/simple-tcp-comm/client.py status "$N"
```

## Expected output

Logcat:
```
AutoSync: triggering SyncService.sync()
AutoSync: result: ... total=N
```

Job status:
```
status: done
task: ingest_unified_payload
device_id: sdk_gphone64_x86_64
schema_version: 5
worker: e2e-YYYYMMDD_HHMMSS-app7-hierarchy-verify
accepted: True
```

## Pass criteria

- Logcat shows `AutoSync` trigger + `submit ok`
- Job on DO queue has `task: ingest_unified_payload`
- `device_id` matches emulator (NOT `e2e-test-device-001` or any fake ID)
- Worker acked with `accepted: True`
- Worker name matches the `e2e-*` worker from `setup_e2e_local.sh`

## Fail criteria

- No `submit ok` in logcat → `TcpQueueSyncApi` can't reach the queue (network/firewall)
- Job exists but `accepted: False` → schema mismatch or worker bug
- `device_id` is a Python test string → this was a fake payload, not the real app

## Current status

- [ ] Not started
- [ ] In progress
- [ ] Verified

## Evidence

(fill in after auto-sync fires)
