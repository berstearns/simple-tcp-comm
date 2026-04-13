# Deploy Timeline Tracker on Archive DB via tmux send-keys

> Verified 2026-04-13 on `archlinux` (bernardo-pc). Single `tmux send-keys` to a named pane.

## Context

Same as the worker timeline tracker, but reads from the **archive DB** instead of the worker DB. Shows all collected data with `_source_worker` attribution. Use this to confirm data is flowing through the full pipeline: app → queue → worker → drain → receiver → archive.

The archive DB is written by the `archive_receiver` drain/receiver pair. The drain pushes data from the worker DB to the receiver, which inserts into the archive.

## Prerequisites

- tmux pane already exists and is named (e.g., `archive-tracker-20260413`)
- Archive DB exists and has data (drain + receiver must have run at least once)
- `show_timeline.sh` exists in the repo (comes with `git clone`)

## The Command

```bash
PANE="%XX"                                                              # tmux pane ID
REPO="/home/b/simple-tcp-comm-worker-20260413"                          # git clone path
ARCHIVE_DB="${REPO}/dbs/archive.db"                                     # archive written by receiver

tmux send-keys -t ${PANE} "watch -n 5 ${REPO}/show_timeline.sh ${ARCHIVE_DB}" C-m
```

## Finding your pane

```bash
tmux list-panes -a -F '#{pane_id} #{pane_title}' | grep archive-tracker
```

## What it shows

Same as the worker timeline tracker — all activity sorted by time (most recent first), refreshing every 5s. The difference: this data has been through the full pipeline (app → queue → worker → drain → TCP → receiver → archive). If it shows up here, every stage worked.

```
══════════════════════════════════════════════════════════════
  READING TIMELINE   15:40:12
  /home/b/simple-tcp-comm-worker-20260413/dbs/archive.db
══════════════════════════════════════════════════════════════

── All Activity (most recent first) ──
       time          type             comic_id          device_id              detail
-------------------  ----------  --------------------  -------------------  --------
2026-04-13 13:08:05  DOUBLE_TAP  histoire-de-l-art-hq  sdk_gphone64_x86_64  chapter_01...
2026-04-13 13:08:04  SWIPE_NEXT  histoire-de-l-art-hq  sdk_gphone64_x86_64  chapter_01...
2026-04-13 13:08:04  PAGE        histoire-de-l-art-hq  sdk_gphone64_x86_64  chapter_01...
...

── Totals ──
14 page enters
19 interactions
3 annotations
```

## Difference from worker timeline

| | Worker timeline | Archive timeline |
|---|---|---|
| DB | `dbs/app7.db` | `dbs/archive.db` |
| Data source | Worker ingested directly from queue | Drained from worker via TCP receiver |
| Extra columns | — | `_source_worker`, `_archive_id` |
| Proves | Queue → worker works | Full pipeline works (including drain + receiver) |

## Stopping

`Ctrl-C` in the pane stops `watch`. The pane stays open.

## Adapting for different archive DBs

```bash
# Different worker instance archive
ARCHIVE_DB="/home/b/simple-tcp-comm-worker-20260412/dbs/archive.db"
tmux send-keys -t ${PANE} "watch -n 5 ${REPO}/show_timeline.sh ${ARCHIVE_DB}" C-m

# Archive from a different worker instance
ARCHIVE_DB="/home/b/simple-tcp-comm-worker-deploy/offline-collected/20260412_203149/archive.db"
tmux send-keys -t ${PANE} "watch -n 5 ${REPO}/show_timeline.sh ${ARCHIVE_DB}" C-m
```

## Adapting for a remote server

```bash
ssh root@<REMOTE_IP> "
  tmux send-keys -t <PANE> 'watch -n 5 /root/simple-tcp-comm-worker-20260413/show_timeline.sh /root/simple-tcp-comm-worker-20260413/dbs/archive.db' C-m
"
```

## Naming convention

| Resource | Name |
|---|---|
| tmux pane title | `archive-tracker-YYYYMMDD` |
| Script | `show_timeline.sh` (in repo root) |
| Target DB | `dbs/archive.db` inside the worker's git clone |
