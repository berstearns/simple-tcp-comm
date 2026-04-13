# Deploy Timeline Tracker via tmux send-keys

> Verified 2026-04-13 on `archlinux` (bernardo-pc). Single `tmux send-keys` to a named pane.

## Context

The timeline tracker is a live view of all user interactions stored in a worker's DB — pages entered, swipes, taps, bubble annotations — sorted by timestamp, refreshing every 5 seconds. It runs `watch -n 5` against `show_timeline.sh` which queries the worker DB directly via sqlite3.

Used for: watching real-time user activity as it flows from the Android app → DO queue → worker DB. You open the app, tap around, and within ~60s (auto-sync interval) the timeline pane shows your actions.

## Prerequisites

- tmux pane already exists and is named (e.g., `timeline`)
- Worker DB exists and has data (worker must be running and ingesting)
- `show_timeline.sh` exists in the repo (at `/home/b/simple-tcp-comm/show_timeline.sh`)

## The Command

```bash
PANE="%55"                                                        # tmux pane ID (find with: tmux list-panes -a -F '#{pane_id} #{pane_title}')
DB="/home/b/simple-tcp-comm-worker-20260413/dbs/app7.db"          # worker DB path

tmux send-keys -t ${PANE} "watch -n 5 /home/b/simple-tcp-comm/show_timeline.sh ${DB}" C-m
```

That's it. One command.

## Finding your pane ID

```bash
# List all panes with their titles and IDs
tmux list-panes -a -F '#{pane_id} #{pane_title} #{session_name}:#{window_name}'

# Or filter for your named pane
tmux list-panes -a -F '#{pane_id} #{pane_title}' | grep timeline
```

## What it shows

Three sections, all sorted by timestamp:

```
══════════════════════════════════════════════════════════════
  READING TIMELINE   13:10:51
  /home/b/simple-tcp-comm-worker-20260413/dbs/app7.db
══════════════════════════════════════════════════════════════

── Pages Entered ──
       time                comic_id            chapter_name              page_title
-------------------  --------------------  ---------------------  ----------------------
2026-04-13 12:57:08  histoire-de-l-art-hq  chapter_01_pages_5-26  chapter_01_pages_5-26
2026-04-13 12:57:09  histoire-de-l-art-hq  chapter_01_pages_5-26  chapter_01_pages_5-26
...

── Page Interactions ──
       time          interaction_type        comic_id            chapter_name
-------------------  ----------------  --------------------  ---------------------
2026-04-13 12:57:05  DOUBLE_TAP        histoire-de-l-art-hq  chapter_01_pages_5-26
2026-04-13 12:57:08  SWIPE_NEXT        histoire-de-l-art-hq  chapter_01_pages_5-26
...

── Bubble Taps ──
       time              label       region_type            image_id
-------------------  --------------  -----------  -----------------------------
2026-04-13 12:57:06  understood      BUBBLE       chapter_01_pages_5-26/page_11
2026-04-13 12:57:12  partially       BUBBLE       chapter_01_pages_5-26/page_12
2026-04-13 12:57:14  not_understood  BUBBLE       chapter_01_pages_5-26/page_13

── Totals ──
14 page enters
19 interactions
3 bubble taps
```

## What `show_timeline.sh` does

Located at `/home/b/simple-tcp-comm/show_timeline.sh`. Runs 4 sqlite3 queries:

1. `SELECT ... FROM session_events WHERE event_type = 'PAGE_ENTER' ORDER BY timestamp` — pages visited
2. `SELECT ... FROM page_interactions ORDER BY timestamp` — swipes, taps, zooms
3. `SELECT ... FROM annotation_records ORDER BY timestamp` — bubble label taps (understood/partially/not_understood)
4. Totals — one-line count of each

All timestamps rendered as `datetime(timestamp/1000, 'unixepoch', 'localtime')`.

## Stopping

`Ctrl-C` in the pane stops `watch`. The pane stays open.

## Adapting for different DBs

Just change the `DB` variable. Point it at any worker DB:

```bash
# Different worker instance
DB="/home/b/simple-tcp-comm-worker-20260412/dbs/app7.db"
tmux send-keys -t ${PANE} "watch -n 5 /home/b/simple-tcp-comm/show_timeline.sh ${DB}" C-m

# Archive DB (has _source_worker column, queries still work)
DB="/home/b/simple-tcp-comm-worker-deploy/offline-collected/20260412_203149/archive.db"
tmux send-keys -t ${PANE} "watch -n 5 /home/b/simple-tcp-comm/show_timeline.sh ${DB}" C-m
```

## Adapting for a remote server

On a remote machine, `show_timeline.sh` comes from the git clone:

```bash
ssh root@<REMOTE_IP> "
  tmux send-keys -t <PANE> 'watch -n 5 /root/simple-tcp-comm-worker-20260413/show_timeline.sh /root/simple-tcp-comm-worker-20260413/dbs/app7.db' C-m
"
```

## Naming convention

| Resource | Name |
|---|---|
| tmux pane title | `timeline` |
| Script | `show_timeline.sh` (in repo root, comes with git clone) |
| Target DB | whichever worker's `dbs/app7.db` you want to watch |
