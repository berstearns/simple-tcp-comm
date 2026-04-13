# 11 — Emulator App Generates Room Rows from Real User Actions

**Owner:** implementer (manual — requires using the app)
**Depends on:** APK installed, emulator booted

## Success criterion

After browsing at least one comic and tapping on at least one page in the Android app, the emulator's Room DB has:
- `session_events` rows with `synced=0` (APP_START, PAGE_ENTER, PAGE_LEAVE, etc.)
- `page_interactions` rows with `synced=0` (TAP, SWIPE_NEXT, DOUBLE_TAP, etc.)
- `comicId` on those rows is NOT `_no_comic_` (the real asset ID from `settingsStore`)

This confirms the producer-side Kotlin logging path works: `AndroidSessionRepository` / `AndroidLearnerDataRepository` → Room entities → `synced=0`.

## How to verify

```bash
# After using the app for at least 30 seconds:
adb exec-out run-as pl.czak.imageviewer.app7 sqlite3 databases/learner_data.db <<'SQL'
SELECT 'session_events unsynced=' || COUNT(*) FROM session_events WHERE synced=0;
SELECT 'page_interactions unsynced=' || COUNT(*) FROM page_interactions WHERE synced=0;
SELECT 'distinct comicIds:' AS '';
SELECT DISTINCT comicId FROM session_events WHERE comicId != '_no_comic_';
SQL
```

## Expected output

```
session_events unsynced=N        (N > 0)
page_interactions unsynced=M     (M > 0)
distinct comicIds:
batch-01-hq-tokens               (or whatever comic the user browsed)
```

## Pass criteria

- `session_events unsynced > 0`
- `page_interactions unsynced > 0`
- At least one `comicId` that is NOT `_no_comic_`

## Fail criteria

- Zero unsynced rows → app not logging (check logcat for crashes)
- All `comicId = '_no_comic_'` → `settingsStore.getString("selected_asset_id")` not populated

## Current status

- [ ] Not started
- [ ] In progress
- [ ] Verified

## Evidence

(fill in after using the app)
