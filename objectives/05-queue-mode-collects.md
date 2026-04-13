# 05 — Queue Mode Collects

**Owner:** implementer
**Depends on:** 04

## Success criterion

Running `collector.py collect --queue` produces an archive with the **same row counts** as `--direct` mode for every table. Queue mode submits `{"task": "query", "db": "app7", "sql": "SELECT * FROM ...", "params": [...]}` jobs to the TCP queue, the worker picks them up, returns `{"cols": [...], "rows": [...]}`, and the collector inserts the results into the archive.

### Prerequisites

- DO queue server must be reachable at `137.184.225.153:9999`
- Worker must be running in tmux `app7-hierarchy-worker` and polling the queue
- Worker must support `query` task type (it does — `worker.py` line 153)

### Queue mode specifics

- Uses `client.submit()` / `client.status()` for each table
- Paginates with `LIMIT 5000 OFFSET` to stay under the server's 1MB payload limit
- No `target` routing (FIFO queue) — works because there's exactly 1 worker polling
- Column names come from the worker's `{"cols": [...]}` response, not from schema introspection

### Known limitation

Queue mode only works correctly with a single worker. With multiple workers, a query job could be picked up by the wrong worker (no `target` routing on the server yet). This is blocked on Strategy 01 (user-worker affinity) from `docs/implementation_plan/01-user-worker-affinity.md`.

## How to verify

```bash
# 1. Confirm worker is alive
python3 /home/b/simple-tcp-comm/client.py workers | grep hierarchy-verify

# 2. Collect via queue
rm -f /tmp/test-archive-queue.db
ARCHIVE_DB=/tmp/test-archive-queue.db python3 /home/b/simple-tcp-comm/collector.py collect \
  --queue --worker-name bernardo-pc-app7-hierarchy-verify --db app7

# 3. Collect via direct (reference)
rm -f /tmp/test-archive-direct.db
ARCHIVE_DB=/tmp/test-archive-direct.db python3 /home/b/simple-tcp-comm/collector.py collect \
  --direct /home/b/simple-tcp-comm-local-state/app7-hierarchy-verify.db \
  --worker-name bernardo-pc-app7-hierarchy-verify

# 4. Compare row counts
for t in comics chapters pages images ingest_batches session_events annotation_records \
         chat_messages page_interactions app_launch_records settings_changes \
         region_translations app_sessions comic_sessions chapter_sessions page_sessions; do
  q=$(sqlite3 /tmp/test-archive-queue.db "SELECT COUNT(*) FROM $t;")
  d=$(sqlite3 /tmp/test-archive-direct.db "SELECT COUNT(*) FROM $t;")
  echo "$t: queue=$q direct=$d match=$([ "$q" = "$d" ] && echo YES || echo NO)"
done
```

## Expected output

All 16 tables show `match=YES`.

## Pass criteria

- Queue-mode archive has identical row counts to direct-mode archive for all 16 tables
- No timeouts during collection
- `collection_log` entries exist for all 16 tables
- No errors in collector output

## Fail criteria

- Worker unreachable (queue mode fails with timeout)
- Row count mismatch between queue and direct modes
- Pagination bug (queue mode collects fewer rows than direct mode for large tables)
- Column name mismatch between worker response and archive schema

## Current status

- [ ] Not started
- [ ] In progress
- [x] Verified

## Evidence

Verified 2026-04-12.

After adding current IP (`217.22.135.247`) to DO firewall and starting queue server via `deploy-queue start`, queue mode collected all 16 tables successfully (run `5fa371ed`).

Comparison: all 16 tables `match=YES` between queue-mode archive and direct-mode archive:
```
comics: queue=2 direct=2 match=YES
ingest_batches: queue=2 direct=2 match=YES
app_sessions: queue=2 direct=2 match=YES
comic_sessions: queue=2 direct=2 match=YES
(12 remaining tables: queue=0 direct=0 match=YES)
```

Worker: `bernardo-pc-app7-hierarchy-verify-app7-hierarchy-verify`, tmux `app7-hierarchy-worker`, polling DO queue every 2s. Each table's query job was submitted via `client.submit()`, picked up by the worker, result polled via `client.status()`, and inserted into archive with `INSERT OR IGNORE`.
