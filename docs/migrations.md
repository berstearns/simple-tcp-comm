# Database Migration Patterns

All migrations run via `migrate.sh` on every deploy. Every operation **must be idempotent** (safe to re-run).

Helpers available in `migrate.sh`:
- `run_sql <db_path> <description> <sql>` — run any idempotent SQL
- `add_column_if_missing <db_path> <table> <column> <type>` — safe ALTER TABLE

---

## 1. Create a new table

The simplest migration. Use `CREATE TABLE IF NOT EXISTS`.

```bash
run_sql "${DBS[main]}" "create users table" \
    "CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );"
```

## 2. Create a related table (foreign key)

Example: a user starts learning sessions. One user has many sessions.

```bash
run_sql "${DBS[main]}" "create learning_sessions table" \
    "CREATE TABLE IF NOT EXISTS learning_sessions (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        topic TEXT,
        started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        ended_at DATETIME,
        status TEXT DEFAULT 'active'
    );"
```

Note: SQLite does not enforce foreign keys by default. To enable:

```bash
run_sql "${DBS[main]}" "enable foreign keys" \
    "PRAGMA foreign_keys = ON;"
```

## 3. Add a column to an existing table

Example: add `duration_minutes` to learning_sessions after the table already exists in production.

```bash
add_column_if_missing "${DBS[main]}" "learning_sessions" "duration_minutes" "INTEGER"
```

SQLite limitation: `ALTER TABLE` can only ADD columns, not drop or rename them (rename supported in SQLite >= 3.25.0).

## 4. Add an index

Speed up queries like "get all sessions for a user".

```bash
run_sql "${DBS[main]}" "index learning_sessions by user_id" \
    "CREATE INDEX IF NOT EXISTS idx_learning_sessions_user_id
     ON learning_sessions(user_id);"
```

Composite index for queries filtering by user + status:

```bash
run_sql "${DBS[main]}" "index learning_sessions by user+status" \
    "CREATE INDEX IF NOT EXISTS idx_learning_sessions_user_status
     ON learning_sessions(user_id, status);"
```

## 5. Add a default value via backfill

When adding a column that needs existing rows populated:

```bash
add_column_if_missing "${DBS[main]}" "users" "role" "TEXT DEFAULT 'learner'"

run_sql "${DBS[main]}" "backfill users.role" \
    "UPDATE users SET role = 'learner' WHERE role IS NULL;"
```

## 6. Create a junction table (many-to-many)

Example: users can tag learning sessions with multiple topics.

```bash
run_sql "${DBS[main]}" "create session_topics table" \
    "CREATE TABLE IF NOT EXISTS session_topics (
        session_id INTEGER NOT NULL REFERENCES learning_sessions(id),
        topic_id INTEGER NOT NULL REFERENCES topics(id),
        PRIMARY KEY (session_id, topic_id)
    );"
```

## 7. Rename a column (SQLite >= 3.25.0)

```bash
run_sql "${DBS[main]}" "rename learning_sessions.topic to subject" \
    "ALTER TABLE learning_sessions RENAME COLUMN topic TO subject;"
```

Not idempotent by default — wrap with a check:

```bash
existing=$(sqlite3 "${DBS[main]}" "PRAGMA table_info(learning_sessions);" | cut -d'|' -f2)
if echo "$existing" | grep -qw "topic"; then
    sqlite3 "${DBS[main]}" "ALTER TABLE learning_sessions RENAME COLUMN topic TO subject;"
    log "OK   renamed topic -> subject"
else
    log "SKIP topic already renamed"
fi
```

## 8. Create a view

Aggregate data without storing it. Idempotent with `CREATE VIEW IF NOT EXISTS` (SQLite >= 3.39.0) or drop-and-recreate:

```bash
run_sql "${DBS[main]}" "create user_stats view" \
    "DROP VIEW IF EXISTS user_stats;
     CREATE VIEW user_stats AS
     SELECT
         u.id,
         u.name,
         COUNT(ls.id) AS total_sessions,
         SUM(ls.duration_minutes) AS total_minutes
     FROM users u
     LEFT JOIN learning_sessions ls ON ls.user_id = u.id
     GROUP BY u.id;"
```

## 9. Seed initial data

Insert default rows only if they don't exist:

```bash
run_sql "${DBS[main]}" "seed default topics" \
    "INSERT OR IGNORE INTO topics(id, name) VALUES
        (1, 'vocabulary'),
        (2, 'grammar'),
        (3, 'listening'),
        (4, 'reading');"
```

---

## Migration order for the user -> learning_sessions example

Add these to `migrate.sh` in order:

```bash
# 1. tables
run_sql "${DBS[main]}" "create users table" \
    "CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );"

run_sql "${DBS[main]}" "create learning_sessions table" \
    "CREATE TABLE IF NOT EXISTS learning_sessions (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        topic TEXT,
        started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        ended_at DATETIME,
        status TEXT DEFAULT 'active'
    );"

# 2. indexes
run_sql "${DBS[main]}" "index learning_sessions by user_id" \
    "CREATE INDEX IF NOT EXISTS idx_learning_sessions_user_id
     ON learning_sessions(user_id);"

# 3. later additions
add_column_if_missing "${DBS[main]}" "learning_sessions" "duration_minutes" "INTEGER"
add_column_if_missing "${DBS[main]}" "learning_sessions" "score" "REAL"
```

---

## Tricky migration scenarios

### 10. Change a column type (SQLite can't ALTER type)

SQLite has no `ALTER COLUMN`. You must recreate the table.

Problem: `learning_sessions.topic` is TEXT but you want it to be an INTEGER FK to a `topics` table.

```bash
# Only run if the old schema is still in place
col_type=$(sqlite3 "${DBS[main]}" "PRAGMA table_info(learning_sessions);" \
    | grep '|topic|' | cut -d'|' -f3)

if [ "$col_type" = "TEXT" ]; then
    sqlite3 "${DBS[main]}" "
        BEGIN;
        ALTER TABLE learning_sessions RENAME TO _ls_old;
        CREATE TABLE learning_sessions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            topic_id INTEGER REFERENCES topics(id),
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            ended_at DATETIME,
            status TEXT DEFAULT 'active'
        );
        INSERT INTO learning_sessions(id, user_id, started_at, ended_at, status)
            SELECT id, user_id, started_at, ended_at, status FROM _ls_old;
        DROP TABLE _ls_old;
        COMMIT;
    "
    log "OK   recreated learning_sessions with topic_id FK"
else
    log "SKIP learning_sessions already migrated"
fi
```

Danger: this drops any data in the old `topic` TEXT column. Map it first if you need it.

### 11. Add NOT NULL column to table with existing rows

`ALTER TABLE ADD COLUMN ... NOT NULL` fails if rows already exist and there's no default.

```bash
# Wrong — will fail if users table has rows:
#   add_column_if_missing "${DBS[main]}" "users" "role" "TEXT NOT NULL"

# Right — add with default, then optionally remove default in a table rebuild:
add_column_if_missing "${DBS[main]}" "users" "role" "TEXT NOT NULL DEFAULT 'learner'"
```

### 12. Split one table into two (normalize)

Problem: `learning_sessions` has a raw `topic TEXT` but you want a proper `topics` table.

```bash
# Step 1: create topics table
run_sql "${DBS[main]}" "create topics table" \
    "CREATE TABLE IF NOT EXISTS topics (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE NOT NULL
    );"

# Step 2: migrate existing data (idempotent — INSERT OR IGNORE)
run_sql "${DBS[main]}" "extract topics from sessions" \
    "INSERT OR IGNORE INTO topics(name)
     SELECT DISTINCT topic FROM learning_sessions
     WHERE topic IS NOT NULL;"

# Step 3: add topic_id column
add_column_if_missing "${DBS[main]}" "learning_sessions" "topic_id" "INTEGER REFERENCES topics(id)"

# Step 4: backfill the FK
run_sql "${DBS[main]}" "backfill topic_id" \
    "UPDATE learning_sessions SET topic_id = (
         SELECT id FROM topics WHERE topics.name = learning_sessions.topic
     ) WHERE topic_id IS NULL AND topic IS NOT NULL;"

# Step 5: topic column is now dead weight — leave it or drop via table rebuild
```

Order matters here. Each step is idempotent, but they must run sequentially.

### 13. Merge two columns into one (computed)

Problem: `ended_at - started_at` should be stored as `duration_minutes`.

```bash
add_column_if_missing "${DBS[main]}" "learning_sessions" "duration_minutes" "INTEGER"

run_sql "${DBS[main]}" "backfill duration_minutes" \
    "UPDATE learning_sessions
     SET duration_minutes = CAST(
         (julianday(ended_at) - julianday(started_at)) * 1440 AS INTEGER
     )
     WHERE ended_at IS NOT NULL AND duration_minutes IS NULL;"
```

### 14. Delete rows safely (with backup)

Problem: purge old sessions but keep a safety net.

```bash
# Backup before destructive operation
run_sql "${DBS[main]}" "archive old sessions" \
    "CREATE TABLE IF NOT EXISTS learning_sessions_archive AS
     SELECT * FROM learning_sessions WHERE 0;

     INSERT INTO learning_sessions_archive
     SELECT * FROM learning_sessions
     WHERE ended_at < datetime('now', '-90 days')
     AND id NOT IN (SELECT id FROM learning_sessions_archive);

     DELETE FROM learning_sessions
     WHERE ended_at < datetime('now', '-90 days');"
```

### 15. Migration that must run exactly once (not idempotent)

Some operations can't be made idempotent (e.g., hashing plaintext passwords). Use a migration log.

```bash
run_sql "${DBS[main]}" "create migration_log" \
    "CREATE TABLE IF NOT EXISTS migration_log (
        name TEXT PRIMARY KEY,
        ran_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );"

already_ran() {
    local count
    count=$(sqlite3 "${DBS[main]}" \
        "SELECT COUNT(*) FROM migration_log WHERE name='$1';")
    [ "$count" -gt 0 ]
}

if ! already_ran "hash_emails_v1"; then
    sqlite3 "${DBS[main]}" "
        UPDATE users SET email = lower(trim(email)) WHERE email IS NOT NULL;
        INSERT INTO migration_log(name) VALUES('hash_emails_v1');
    "
    log "OK   hash_emails_v1"
else
    log "SKIP hash_emails_v1 already ran"
fi
```

### 16. Concurrent workers: migration race condition

Problem: two workers start simultaneously, both run `migrate.sh`, both try to create the same table.

SQLite handles this via its file lock — `CREATE TABLE IF NOT EXISTS` is atomic. But multi-statement migrations (like the table rebuild in #10) need explicit transactions:

```bash
sqlite3 "${DBS[main]}" "
    BEGIN IMMEDIATE;  -- grabs write lock immediately
    -- ... all migration statements ...
    COMMIT;
"
```

`BEGIN IMMEDIATE` prevents a second connection from starting a conflicting write. Without it, two connections could both read the old schema, then both try to write.
