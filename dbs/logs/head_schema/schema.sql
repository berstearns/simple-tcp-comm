-- logs.db — system event log
--
-- ┌─────────────────────┐
-- │ events              │
-- ├─────────────────────┤
-- │ id    PK            │
-- │ type  TEXT NN   [ix]│
-- │ msg   TEXT          │
-- │ ts    TEXT NN   [ix]│
-- └─────────────────────┘
--
-- ix: idx_events_type, idx_events_ts
--

PRAGMA journal_mode = WAL;

CREATE TABLE events (
    id   INTEGER PRIMARY KEY,
    type TEXT    NOT NULL,
    msg  TEXT,
    ts   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX idx_events_type ON events(type);
CREATE INDEX idx_events_ts   ON events(ts);
