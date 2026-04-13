# Archive Receiver — Swappable Serialization Variants

TCP archive receiver with admission control (header/verdict/receipt protocol).
Three serialization variants — swap by running a different receiver + drain pair.

## Directory layout

```
archive_receiver/
├── protocol.py          ← shared: header/verdict/receipt pack/unpack
├── receiver_base.py     ← shared: admission control + archive insert
├── drain_base.py        ← shared: drain loop + adaptive batch sizing
├── json_plain/          ← variant 1: raw JSON (flags=0x00)
│   ├── receiver.py
│   └── drain.py
├── json_zlib/           ← variant 2: zlib-compressed JSON (flags=0x01)
│   ├── receiver.py
│   └── drain.py
└── struct_pack/         ← variant 3: binary struct-packed rows (flags=0x02)
    ├── schema_registry.py  ← fixed struct formats per table
    ├── receiver.py
    └── drain.py
```

## Quick test (any variant)

```bash
# Terminal 1: start receiver
ARCHIVE_DB=/tmp/test-archive.db ARCHIVE_PORT=8080 \
  python3 archive_receiver/json_zlib/receiver.py

# Terminal 2: run drain (one-shot against a worker DB)
WORKER_DB=/path/to/app7.db ARCHIVE_HOST=127.0.0.1 ARCHIVE_PORT=8080 \
  python3 archive_receiver/json_zlib/drain.py --once
```

## Switching variants

Just change the subfolder — the protocol is identical:

```bash
# json plain
python3 archive_receiver/json_plain/receiver.py
python3 archive_receiver/json_plain/drain.py --once

# json + zlib (recommended)
python3 archive_receiver/json_zlib/receiver.py
python3 archive_receiver/json_zlib/drain.py --once

# struct pack (fastest, rigid schema)
python3 archive_receiver/struct_pack/receiver.py
python3 archive_receiver/struct_pack/drain.py --once
```

## Environment variables

| Variable | Default | Used by |
|---|---|---|
| `ARCHIVE_DB` | `/tmp/archive-receiver-test.db` | receiver |
| `ARCHIVE_PORT` | `8080` | receiver + drain |
| `ARCHIVE_HOST` | `127.0.0.1` | drain |
| `WORKER_DB` | (required) | drain |
| `WORKER_NAME` | `drain-worker` | drain |
| `DRAIN_INTERVAL` | `300` | drain (seconds between cycles) |
| `COLD_AGE_MS` | `3600000` | drain (rows older than this are "cold") |

## Protocol

All variants share the same binary protocol:

1. Worker sends **HEADER** (16 bytes): payload_size, row_count, table_id, flags
2. Receiver sends **VERDICT** (12 bytes): ACCEPT/REJECT/SHRINK + suggested batch size
3. Worker sends **PAYLOAD** (variable): only if ACCEPT
4. Receiver sends **RECEIPT** (12 bytes): inserted, skipped, suggested next batch size

The `flags` byte in the header tells the receiver which serialization format the payload uses.
