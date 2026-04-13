# Local E2E Deployment — Setup and Verification

> From conversation: setting up a real E2E test with tmux session, worker, collector, and Android emulator.

## One-command setup

```bash
/home/b/simple-tcp-comm/setup_e2e_local.sh
```

Creates:
- Timestamped `dbs/YYYYMMDD_HHMMSS/app7.db` (worker DB)
- Timestamped `offline-collected/YYYYMMDD_HHMMSS/archive.db` (collector output)
- tmux session `app7-e2e` with named windows and panes

## tmux session layout

| Window | Pane | What |
|--------|------|------|
| `pipeline` | top (0) | Worker polling DO queue |
| `pipeline` | bottom (1) | Collector loop (60s cycle: collect + verify) |
| `inspect` | top | Worker DB summary (watch -n 5) |
| `inspect` | bottom | Archive DB summary (watch -n 5) |
| `timeline` | single | Chronological reading timeline from archive |

## Navigation

- `tmux attach -t app7-e2e` — attach
- `Ctrl-B n` / `Ctrl-B p` — next/previous window
- `Ctrl-B ↑` / `Ctrl-B ↓` — switch panes
- `Ctrl-B D` — detach

## Real E2E flow (no fake payloads)

1. Run `setup_e2e_local.sh`
2. Boot emulator, install APK
3. `adb shell am start -n pl.czak.imageviewer.app7/pl.czak.learnlauncher.android.MainActivity --ez auto_sync true`
4. Use the app: browse comics, tap pages, swipe
5. Wait 60s for auto-sync
6. Worker pane shows `ingesting... accepted=True`
7. Collector pane shows `N new` rows and `OVERALL: PASS (16/16)`

## Proof it's real (not a Python script)

- `device_id = sdk_gphone64_x86_64` (emulator, not a fake string)
- `comic_id` matches what you actually browsed (e.g., `chainsawman-fr-lq`)
- Logcat shows `AutoSync: triggering SyncService.sync()` + `submit ok id=NNNN`
- Job on DO queue shows `task: ingest_unified_payload`, acked by the E2E worker

## Directory layout

```
/home/b/simple-tcp-comm-worker-deploy/
├── .env.e2e-YYYYMMDD_HHMMSS
├── dbs/
│   └── YYYYMMDD_HHMMSS/
│       └── app7.db
└── offline-collected/
    └── YYYYMMDD_HHMMSS/
        └── archive.db
```

## Key files

| File | Purpose |
|------|---------|
| `/home/b/simple-tcp-comm/setup_e2e_local.sh` | One-command E2E setup |
| `/home/b/simple-tcp-comm/deploy_e2e_local.md` | Detailed step-by-step instructions |
| `/home/b/simple-tcp-comm/collector.py` | Offline collector |
| `/home/b/simple-tcp-comm/show_timeline.sh` | Reading timeline query script |
| `/home/b/simple-tcp-comm/objectives/10-14` | Real-app E2E objectives |
