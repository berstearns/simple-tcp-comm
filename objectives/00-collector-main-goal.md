# 00 — Collector Main Goal: Worker Data Consolidated into Archive

**Owner:** implementer
**Depends on:** all of 01-07

## Success criterion

`collector.py` exists at `/home/b/simple-tcp-comm/collector.py` and can:

1. Create an archive DB from scratch with all 17 tables (16 data + `collection_log`)
2. Collect all rows from a worker DB into the archive via `--direct` mode
3. Collect incrementally (only new rows since last run) using watermarks stored in `collection_log`
4. Survive watermark loss without duplicating data (`INSERT OR IGNORE` on UNIQUE constraints)
5. Collect via `--queue` mode (submitting `query` jobs through the TCP queue)
6. Show collection history via `status` subcommand
7. Prune old data from the archive via `prune --days N`
8. Verify archive matches worker via `verify` subcommand (per-table row count comparison, exit 0)

## How to verify

This is a composite objective — it is "Verified" only when **all** sub-objectives are checked off.

### Sub-objectives

- [x] 01 — Archive schema creates cleanly (17 tables, `_source_worker` on all data tables)
- [x] 02 — Direct mode collects all 16 data tables
- [x] 03 — Incremental watermark works (second run = 0 new rows)
- [x] 04 — Idempotent re-collection (INSERT OR IGNORE catches dupes after watermark wipe)
- [x] 05 — Queue mode collects (all 16 tables match between queue and direct)
- [x] 06 — Status + prune subcommands
- [x] 07 — Verify subcommand (row counts match, exit 0)

## Current status

- [ ] Not started
- [ ] In progress
- [x] Verified **(7/7 all green)**

## Evidence

Verified 2026-04-12. All 7 sub-objectives pass with evidence.

Key results:
- Archive schema: 17 tables, all with `_source_worker` column
- Direct collect: `OVERALL: PASS (16/16 tables match)`
- Queue collect: all 16 tables `match=YES` vs direct mode
- Incremental: second run = 0 new rows for watermarked tables
- Idempotent: after watermark wipe, re-collect = 0 new, 8 skipped
- Prune: correctly deletes timestamp-bearing rows, preserves catalog
- Verify: exit 0 on match, exit 1 on mismatch
