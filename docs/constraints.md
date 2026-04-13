# Architectural Constraints

This document records the load-bearing constraints that shape this repo.
Anyone (human or LLM) proposing a design change should re-derive from
these first. Most "simplifications" that look appealing in isolation
violate one of these and break the system.

## Constraint 1 — Workers are behind NAT

Worker hosts (`atlas`, `titan`, `bernardo-pc`, any future homelab box)
can make **outbound** TCP connections but cannot accept inbound ones.
There is no port forwarding, no reverse tunnel, no VPN.

The only publicly reachable machine is `neptune` (Digital Ocean). It
hosts the queue server and `jobs.db`. Nothing else.

**What this forces:**

- Workers must pull work, not have it pushed to them. Hence the polling
  TCP client pattern in `workers/*/worker.py`.
- The data (`app7.db`, `ll.db`, `main.db`, `logs.db`) lives on the NAT'd
  worker hosts, **not** on neptune. Neptune only holds `jobs.db`
  (the job queue itself).
- Any external client (a phone, a PC, a CI job) that wants work to
  happen against that data must enqueue via neptune. It cannot talk to
  the worker directly and it cannot talk to the data directly.
- An HTTP endpoint that tries to run a handler "in-process" on neptune
  is writing to the wrong place — the DB isn't there.

**Anti-patterns this rules out:**

- "Just skip the queue and call the handler directly from the HTTP
  endpoint." — impossible. neptune doesn't have the DB.
- "Put the ingest endpoint on the worker host." — impossible. The
  worker host isn't reachable.
- "Have the phone connect to the worker over a websocket." — impossible.
  Same reason.

## Constraint 2 — Scale must be controllable

Throughput is set by the number of workers draining `jobs.db`, not by
the rate at which clients submit. Adding a worker on a new homelab box
increases throughput. Removing one decreases it. The queue depth in
`jobs.db` is the backpressure signal.

**What this forces:**

- Request-handling must be decoupled from job execution. An HTTP
  endpoint that blocks until a worker picks up its job and returns a
  result couples client-visible latency to `QUEUE_POLL` + worker
  execution time, and makes the endpoint a serial bottleneck — losing
  the point of having N parallel workers.
- Synchronous "submit and wait for result" is only acceptable for
  interactive CLI use (`client.py status <id>`), not for any
  high-traffic or client-facing path.
- Any public-facing entry point must be **fire-and-forget**: accept the
  payload, write one row into `jobs.db`, return 202 immediately.
  Confirmation (if needed at all) happens on a separate request.

**Anti-patterns this rules out:**

- "Make the HTTP endpoint synchronous so the phone gets real counts
  back." — couples phone latency to worker poll interval and serialises
  everything through one endpoint. Defeats horizontal scaling.
- "Lower `QUEUE_POLL` to 0 for low latency." — wastes CPU, still
  doesn't fix the bottleneck, and papers over the real design error.
- "Add a dedicated worker per client." — defeats the whole pull-model
  + NAT topology.

## Derived design rules

The constraints above imply the following rules for any new integration:

1. **Public ingress lives on neptune, nowhere else.**
   If an external system needs to reach this repo, it hits an endpoint
   on neptune. That endpoint's *only* job is to enqueue.

2. **Enqueue endpoints are thin.**
   Validate envelope shape (required fields present, schema version
   understood), call `client.submit(...)`, return `202 Accepted` with
   the `jobs.db` row id. No business logic. No handler calls.
   No waiting on `client.status`.

3. **Handlers are idempotent.**
   Because enqueue is fire-and-forget and clients may retry on network
   errors, any handler consuming external payloads must tolerate exact
   duplicates. Use natural keys + `INSERT OR IGNORE` / `ON CONFLICT`.
   Example: `app7.session_events` uses `UNIQUE(device_id, local_id)` so
   re-ingesting the same KMP `UnifiedPayload` is a no-op.

4. **Handlers run on the host that owns the data.**
   If a handler touches `app7.db`, it runs on a worker host that has
   `app7.db` on its local disk. Not on neptune. This is a consequence
   of Constraint 1 and it is not negotiable.

5. **"Result" means "queued", not "ingested".**
   An HTTP 202 from an enqueue endpoint means the job row landed in
   `jobs.db`. It does *not* mean any worker has executed it yet, or
   that the ingest succeeded. If a caller needs confirmation of
   execution, it must poll `GET /status/{job_id}` separately.

6. **Audit, don't synchronise.**
   Because callers don't wait for execution, server-side visibility
   into "what actually happened" must come from audit tables written
   by the handler itself. Example: `ingest_batches` in `dbs/app7/`
   records every `UnifiedPayload` consumed, with `ingested_at` and
   per-table row counts. Debugging after the fact reads that table —
   it does not replay the queue.

## Concrete example: the KMP app7 sync endpoint

Context: the KMP Android app (`app7-kmp-unified-sync-export-schema`)
produces a `UnifiedPayload` JSON and POSTs it to `/sync/upload`.
`app7.db` lives on NAT'd worker hosts.

Applying the rules above, the correct topology is:

```
phone POST /sync/upload
  │
  ▼
neptune: tiny HTTP shim
  • validates schema_version, device_id
  • client.submit({"task": "ingest_unified_payload", "db": "app7", ...})
  • returns 202 {accepted: true, job_id: N, counts: <sent>}
  │
  │  (enqueue finishes, shim has already returned to phone)
  ▼
jobs.db row waits in neptune
  │
  ▼
NAT'd worker polls, picks up job, runs _ingest_unified_payload
against its LOCAL app7.db, writes ingest_batches audit row, acks.
```

Phone-visible latency: one HTTPS RTT + one `jobs.db` insert.
Not coupled to worker poll interval, not coupled to handler runtime,
not coupled to worker count.

Scale knob: number of workers draining `jobs.db`. Add a box, add
throughput. Backpressure: if `jobs.db` depth exceeds a threshold, the
shim returns 503 and the phone retries later.

What the phone's `SyncResponse.counts` means in this topology: it is
the *sent* count, computed by the shim from the incoming payload
before enqueueing. It is *not* a "rows inserted" confirmation.
Because the handler is idempotent (Rule 3), at-least-once delivery is
already safe — the phone can mark its local rows `synced=1` on 202
without waiting for execution confirmation.

## When to revisit this document

- A new host joins the topology and is *not* behind NAT → Constraint 1
  may relax for that host, but not globally.
- Traffic patterns change such that the queue itself becomes the
  bottleneck (e.g. `jobs.db` insert rate > sqlite write throughput) →
  Constraint 2 still holds, but the implementation of the queue may
  need to change (sharded queues, Redis, etc.). The *rules* above still
  apply; the *mechanism* is what changes.
- Someone proposes removing the queue entirely → re-read this document
  before responding.
