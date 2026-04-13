# 10 — Real App E2E: Android → DO Queue → Worker → Collector → Archive

**Owner:** implementer
**Depends on:** 07 (collector verified), working APK, running emulator

## Success criterion

A **real user session** on the Android emulator (not a crafted Python payload) generates Room DB rows that auto-sync through the DO queue, land in a fresh local worker DB, get collected into an archive, and the verify command confirms all three databases agree.

The entire data path is exercised by real code:
1. Android Room entity logging (Kotlin)
2. `UnifiedPayloadBuilder` serialization (Kotlin)
3. `TcpQueueSyncApi.upload()` TCP send (Kotlin)
4. DO queue server stores the job (Python, remote)
5. Local worker polls, ingests (Python, local)
6. Collector reads worker DB, writes archive (Python, local)

No Python script submits fake payloads. The only input is a human using the app.

## Sub-objectives

- [ ] 11 — Emulator app generates Room rows from real user actions
- [ ] 12 — Auto-sync sends through DO queue (job ID visible on server, acked by worker)
- [ ] 13 — Worker DB has the rows (correct comic_id, no collisions)
- [ ] 14 — Collector archive matches worker DB (`OVERALL: PASS`)

## How to run

```bash
# 1. Setup (creates tmux session with worker + collector)
/home/b/simple-tcp-comm/setup_e2e_local.sh

# 2. Boot emulator + install APK + launch with auto-sync
nohup emulator -avd Pixel_API_34 -no-snapshot-save -no-boot-anim &
adb wait-for-device
adb install -r /home/b/p/minimal-android-apps/app7-explicit-db-hierarchy-bug-fixes_20260410_161800/androidApp/build/outputs/apk/debug/androidApp-debug.apk
adb shell am start -n pl.czak.imageviewer.app7/pl.czak.learnlauncher.android.MainActivity --ez auto_sync true

# 3. Use the app: browse comics, tap pages, swipe, change settings
# 4. Wait 60s for auto-sync
# 5. Watch tmux panes:
#    - Worker pane: "ingesting... accepted=True"
#    - Collector pane: "OVERALL: PASS (16/16)"

# 6. Attach to watch
tmux attach -t app7-e2e
```

## Current status

- [ ] Not started
- [ ] In progress
- [ ] Verified

## Evidence

(fill in after real user session)
