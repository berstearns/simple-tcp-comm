# Scalability: Per-User DBs on a 1/2 vCPU / 1 GB RAM Worker

## Assumptions

- **Worker spec**: 0.5 vCPU, 1 GB RAM, 25 GB disk (typical DO $6/mo droplet)
- **OS + runtime overhead**: ~200 MB RAM (Linux + Python + supervisor)
- **Worker process**: ~50-100 MB RAM (asyncio loop, job handlers)
- **Available RAM for SQLite**: ~600-700 MB
- **SQLite page cache**: default 2 MB per open connection (tunable via `PRAGMA cache_size`)
- **Concurrency**: worker processes 1 job at a time (sequential `poll` loop)
- **Per-user DB**: 6 tables (session_events, annotation_records, chat_messages, page_interactions, app_launch_records, settings_changes)

## Per-User DB Size Estimates

| User activity level | Rows total (6 tables) | DB file size | Notes |
|--------------------|-----------------------|-------------|-------|
| Empty (just created) | 0 | ~48 KB | Schema only, 6 tables |
| Light (1 week) | ~200 | ~100-200 KB | Few sessions, sparse annotations |
| Moderate (1 month) | ~2,000 | ~500 KB - 2 MB | Daily usage, regular annotations |
| Heavy (3+ months) | ~20,000 | ~5-20 MB | Power user, extensive chat + annotations |
| Archival (1 year+) | ~100,000+ | ~30-100 MB | Should be offloaded via collector |

## Scalability Table

| Users on worker | Avg DB size | Total disk | RAM pressure | CPU pressure | Dir listing | Schema migration | Verdict |
|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **10** | 1 MB | 10 MB | None | None | Instant | < 1s | Trivial |
| **50** | 1 MB | 50 MB | None | None | Instant | < 2s | Easy |
| **100** | 2 MB | 200 MB | None | Minimal | Instant | ~5s | Comfortable |
| **250** | 2 MB | 500 MB | None | Minimal | Instant | ~12s | Comfortable |
| **500** | 2 MB | 1 GB | None | Low | Fine | ~25s | Good |
| **1,000** | 2 MB | 2 GB | Low | Low | Fine | ~60s | Good, shard dirs |
| **2,500** | 3 MB | 7.5 GB | Low | Moderate | Slower | ~3 min | Feasible, monitor |
| **5,000** | 3 MB | 15 GB | Moderate | Moderate | Needs sharding | ~6 min | Near disk limit |
| **10,000** | 3 MB | 30 GB | High | High | Needs sharding | ~15 min | Exceeds 25 GB disk |
| **25,000** | 3 MB | 75 GB | Critical | Critical | Needs sharding | ~40 min | Not feasible |

## Bottleneck Analysis

### 1. Disk Space (primary bottleneck)

25 GB disk minus ~3-5 GB for OS/logs/packages = **~20 GB usable**.

| Avg DB size | Max users on 20 GB |
|:-:|:-:|
| 500 KB | ~40,000 |
| 1 MB | ~20,000 |
| 2 MB | ~10,000 |
| 5 MB | ~4,000 |
| 10 MB | ~2,000 |

**Realistic sweet spot**: 500-2,000 users per worker depending on activity level.

### 2. RAM (secondary bottleneck)

SQLite only holds open connections in memory. Since the worker is sequential:
- **1 active connection** at a time = ~2 MB page cache
- **Connection pooling** (if added): 10 cached connections = ~20 MB
- **Fan-out queries**: briefly opens many DBs = spike to ~50-100 MB

600 MB free is more than enough. RAM is **not the bottleneck** for file count.

### 3. CPU (tertiary bottleneck)

0.5 vCPU handles ~50-100 simple queries/sec on SQLite. Bottleneck appears when:
- **Concurrent sync uploads** pile up faster than processing
- **Schema migrations** iterate all files (linear, blocking)
- **Fan-out queries** scan all user DBs

For a language learning app with async syncs, 0.5 vCPU is fine up to ~1,000-2,000 users.

### 4. Filesystem / Inodes

| Users | Files (db + wal + shm) | Impact |
|:-:|:-:|:-:|
| 100 | ~300 | No issue |
| 1,000 | ~3,000 | `ls` slightly slower, shard recommended |
| 10,000 | ~30,000 | Must shard into subdirs |

ext4 default inodes: millions. **Not a practical limit.**
Directory listing performance: degrades past ~10,000 entries in a single dir.

### 5. File Descriptors

Default `ulimit -n`: 1024. Only matters if connections are cached.
Sequential processing = 1 open fd at a time. **Not a bottleneck.**

## Recommended Thresholds

| Threshold | Users per worker | Action |
|-----------|:---:|--------|
| Comfortable | **< 500** | No worries, default setup works |
| Monitor | **500-1,000** | Enable `db_bytes` backpressure reporting, add subdir sharding |
| Migrate | **1,000-2,000** | Add workers, rebalance users via `migrator.py` |
| Hard limit | **~3,000-5,000** | Disk filling up, must add workers or increase disk |

## Planning by Total User Base

| Total users | Workers needed (0.5 vCPU, 1 GB) | Monthly cost (DO) | Notes |
|:-:|:-:|:-:|:-:|
| 50 | 1 | $6 | Single worker, no redundancy |
| 200 | 1 | $6 | Still comfortable |
| 500 | 1 | $6 | Approaching monitor threshold |
| 1,000 | 2 | $12 | 500 users each, headroom for growth |
| 2,500 | 3 | $18 | ~830 users each |
| 5,000 | 5 | $30 | 1,000 users each |
| 10,000 | 10 | $60 | 1,000 users each |
| 25,000 | 15-20 | $90-120 | Diminishing returns, consider bigger droplets |

## Key Takeaway

On a 0.5 vCPU / 1 GB / 25 GB disk worker, **target 500-1,000 user DBs per worker** for a comfortable operating range. The binding constraint is **disk space**, not RAM or CPU. The per-user DB model scales linearly by adding more workers, which aligns with the affinity + migration architecture in strategies 01 and 02.
