# Strategy 05: Per-User Database Files

## Goal

Instead of one shared `main.db` with all users mixed together, give each user their own SQLite file: `/var/lib/myapp/users/u42.db`. This provides natural isolation, trivial migration (file copy), and easy deletion (GDPR: `rm`).

## Dependencies

- **01-user-worker-affinity.md** — routing must exist so the right worker receives each user's jobs

## Why This Over a Shared DB

| Concern | Shared DB + user_id column | Per-user files |
|---------|---------------------------|----------------|
| Migration | Row-by-row SELECT/INSERT | Copy one file |
| Backup one user | Complex query | Copy one file |
| Delete one user (GDPR) | DELETE across 6 tables | `rm user.db` |
| Isolation | WHERE user_id=? everywhere | Automatic |
| Cross-user queries | Easy (one DB) | Harder (fan-out) |
| Schema migrations | One ALTER TABLE | Loop over all files |
| Filesystem overhead | One file | ~100KB per user minimum |

The trade-off is clear: per-user files are better for everything except cross-user analytics (handled by Strategy 06) and migration overhead at scale (mitigated by subdirectory sharding).

## Design

### File Layout

```
/var/lib/myapp/
├── main.db          # shared/system DB (if still needed)
├── logs.db          # shared event log (if still needed)
└── users/
    ├── u42.db       # all data for user u42
    ├── u99.db       # all data for user u99
    └── ...
```

### Per-User DB Schema

Each user DB has the same 6 tables. No `user_id` column needed — the whole file IS that user.

```sql
CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY,
    eventType TEXT,
    timestamp INTEGER,
    durationMs INTEGER,
    chapterName TEXT,
    pageId TEXT,
    pageTitle TEXT,
    synced INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS annotation_records (
    id INTEGER PRIMARY KEY,
    imageId TEXT,
    boxIndex INTEGER,
    boxX REAL, boxY REAL, boxWidth REAL, boxHeight REAL,
    label TEXT,
    timestamp INTEGER,
    tapX REAL, tapY REAL,
    regionType TEXT DEFAULT 'BUBBLE',
    parentBubbleIndex INTEGER,
    tokenIndex INTEGER,
    synced INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY,
    sender TEXT,
    text TEXT,
    timestamp INTEGER,
    synced INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS page_interactions (
    id INTEGER PRIMARY KEY,
    interactionType TEXT,
    timestamp INTEGER,
    chapterName TEXT,
    pageId TEXT,
    normalizedX REAL,
    normalizedY REAL,
    hitResult TEXT,
    synced INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS app_launch_records (
    id INTEGER PRIMARY KEY,
    packageName TEXT,
    timestamp INTEGER,
    currentChapter TEXT,
    currentPageId TEXT,
    synced INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings_changes (
    id INTEGER PRIMARY KEY,
    setting TEXT,
    oldValue TEXT,
    newValue TEXT,
    timestamp INTEGER,
    synced INTEGER DEFAULT 0
);
```

## File Changes

### `worker.py`

#### 1. Add user DB directory config and path resolver

```python
USER_DB_DIR = os.environ.get("USER_DB_DIR", "/var/lib/myapp/users")

# Full schema for new user DBs
USER_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY, eventType TEXT, timestamp INTEGER,
    durationMs INTEGER, chapterName TEXT, pageId TEXT, pageTitle TEXT,
    synced INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS annotation_records (
    id INTEGER PRIMARY KEY, imageId TEXT, boxIndex INTEGER,
    boxX REAL, boxY REAL, boxWidth REAL, boxHeight REAL,
    label TEXT, timestamp INTEGER, tapX REAL, tapY REAL,
    regionType TEXT DEFAULT 'BUBBLE', parentBubbleIndex INTEGER,
    tokenIndex INTEGER, synced INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY, sender TEXT, text TEXT,
    timestamp INTEGER, synced INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS page_interactions (
    id INTEGER PRIMARY KEY, interactionType TEXT, timestamp INTEGER,
    chapterName TEXT, pageId TEXT, normalizedX REAL, normalizedY REAL,
    hitResult TEXT, synced INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS app_launch_records (
    id INTEGER PRIMARY KEY, packageName TEXT, timestamp INTEGER,
    currentChapter TEXT, currentPageId TEXT, synced INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS settings_changes (
    id INTEGER PRIMARY KEY, setting TEXT, oldValue TEXT, newValue TEXT,
    timestamp INTEGER, synced INTEGER DEFAULT 0);
"""

def _user_db_path(user_id):
    """Resolve user ID to a safe filesystem path."""
    safe_id = "".join(c for c in user_id if c.isalnum() or c in "-_")
    if not safe_id:
        raise ValueError(f"invalid user_id: {user_id}")
    return os.path.join(USER_DB_DIR, f"{safe_id}.db")
```

#### 2. Modify `_query` handler to support `user:` DB prefix

```python
@job("query")
def _query(p):
    db_name = p["db"]
    if db_name.startswith("user:"):
        user_id = db_name[5:]
        db_path = _user_db_path(user_id)
    else:
        db_path = DBS[db_name]
    conn = sqlite3.connect(db_path)
    cur = conn.execute(p["sql"], p.get("params", []))
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall() if cols else []
    conn.commit()
    conn.close()
    return {"cols": cols, "rows": rows}
```

#### 3. New job: `init_user_db`

Creates a new user DB with the standard schema. Called when a new user is assigned to this worker.

```python
@job("init_user_db")
def _init_user_db(p):
    user_id = p["user_id"]
    path = _user_db_path(user_id)
    if os.path.exists(path):
        return {"status": "exists", "path": path, "size": os.path.getsize(path)}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(USER_SCHEMA)
    conn.close()
    return {"status": "created", "path": path}
```

#### 4. Stats reporting includes user DB info

Already covered in Strategy 02, but the key addition:

```python
def _db_stats():
    total = 0
    user_count = 0
    if os.path.isdir(USER_DB_DIR):
        for f in os.listdir(USER_DB_DIR):
            if f.endswith(".db"):
                user_count += 1
                try:
                    total += os.path.getsize(os.path.join(USER_DB_DIR, f))
                except OSError:
                    pass
    # Also include shared DBs
    for name, path in DBS.items():
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return {"db_bytes": total, "user_count": user_count}
```

### `infrastructure.sh`

#### 5. Create users/ directory

Add after the existing DB directory creation (step 2):

```bash
USER_DIR="$DB_DIR/users"
if [[ -d "$USER_DIR" ]]; then
    skip "$USER_DIR already exists"
else
    mkdir -p "$USER_DIR"
    ok "created $USER_DIR"
fi
chown "$REAL_USER":"$REAL_USER" "$USER_DIR"
```

Add to `--check` mode:

```bash
if [[ -d "$DB_DIR/users" ]]; then
    ok "user database directory exists ($DB_DIR/users)"
else
    fail "user database directory missing ($DB_DIR/users)"
    errors=$((errors + 1))
fi
```

### `migrate.sh`

#### 6. Iterate per-user DB files for schema changes

Add after the existing migration section:

```bash
# ── Per-user DB migrations ─────────────────────────────────
USER_DIR="${DB_DIR:-/var/lib/myapp}/users"
if [ -d "$USER_DIR" ]; then
    user_db_count=0
    for db_file in "$USER_DIR"/*.db; do
        [ -f "$db_file" ] || continue
        user_db_count=$((user_db_count + 1))

        # Add new migrations here, e.g.:
        # add_column_if_missing "$db_file" "session_events" "new_col" "TEXT"
    done
    log "checked $user_db_count user databases"
else
    log "SKIP no user database directory"
fi
```

### `.env`

#### 7. Add USER_DB_DIR config

```
USER_DB_DIR=/var/lib/myapp/users
```

### `server.py`

#### 8. Auto-create user DB on first assignment

In `resolve_target()` from Strategy 01, after inserting a new affinity row, submit an `init_user_db` job targeted at the assigned worker:

```python
# After: db.execute("INSERT INTO user_affinity(user_id, worker_name) VALUES(?, ?)", ...)
# Queue a job to initialize the user's DB on that worker
db.execute("INSERT INTO jobs(payload, target) VALUES(?, ?)",
    [json.dumps({"task": "init_user_db", "user_id": user_id}), best[0]])
```

## How Sync Data Flows

```
1. Kotlin app syncs:
   POST /sync/upload {userId: "u42", tables: {session_events: [...], ...}}

2. Backend receives, submits job:
   client.submit({"task": "sync_import", "user_id": "u42",
                   "data": {session_events: [...], ...}})

3. Server resolves target via user_affinity → worker-a

4. Worker-a picks up job, opens /var/lib/myapp/users/u42.db

5. Worker inserts rows into the per-user DB

6. Ack → done
```

Note: a `sync_import` job type would need to be added to the worker to handle the bulk insert from the Kotlin app's sync format. This is a thin wrapper that maps the sync payload tables to SQL INSERTs.

## Filesystem Scaling

### Concern: too many files in one directory

At ~1000 users, listing `/users/` is still fast. At 100K+, consider subdirectory sharding:

```
/var/lib/myapp/users/
├── u4/
│   ├── u42.db
│   └── u43.db
├── u9/
│   └── u99.db
```

Use first 2 chars of user_id as subdirectory. Change `_user_db_path`:

```python
def _user_db_path(user_id):
    safe_id = "".join(c for c in user_id if c.isalnum() or c in "-_")
    prefix = safe_id[:2] if len(safe_id) >= 2 else safe_id
    return os.path.join(USER_DB_DIR, prefix, f"{safe_id}.db")
```

Not needed now. Add when you have >1000 users.

## Verification

```bash
# 1. Check infrastructure
./infrastructure.sh --check
# Should show: user database directory exists

# 2. Init a user DB manually
python3 client.py submit '{"task": "init_user_db", "user_id": "test-user-1"}'
# Wait for worker to process
ls /var/lib/myapp/users/
# Should show: test-user-1.db

# 3. Query the user DB
python3 client.py submit '{"task": "query", "db": "user:test-user-1", "sql": "SELECT name FROM sqlite_master WHERE type='\''table'\''"}'
# Should show the 6 tables

# 4. Insert test data
python3 client.py submit '{"task": "query", "db": "user:test-user-1", "sql": "INSERT INTO session_events(eventType, timestamp) VALUES('\''ENTER'\'', 1234567890)"}'

# 5. Read it back
python3 client.py submit '{"task": "query", "db": "user:test-user-1", "sql": "SELECT * FROM session_events"}'
```
