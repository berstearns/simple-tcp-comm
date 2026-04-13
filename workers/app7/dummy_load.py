"""Dummy load for app7 — builds a synthetic UnifiedPayload (schema v3)
and submits it as an ``ingest_unified_payload`` job.

Matches the shape emitted by the KMP producer at
shared/src/commonMain/kotlin/pl/czak/learnlauncher/data/model/UnifiedPayload.kt.

Usage:
    python workers/app7/dummy_load.py [n]       # submit via TCP queue (server must be up)
    python workers/app7/dummy_load.py local [n] # run the handler directly, no queue needed

Either mode auto-applies the schema to the local app7.db first.
"""
import time, random, string, json, sys, os, re, sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import client

REPO_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

def _parse_dbs():
    raw = os.environ.get("QUEUE_DBS", "")
    if raw:
        return dict(pair.split("=", 1) for pair in raw.split(","))
    return {"app7": "/var/lib/myapp/app7.db"}

DBS = _parse_dbs()

def _ensure_schema(db_name, schema_path=None):
    db_path = DBS.get(db_name)
    if not db_path:
        return
    if schema_path is None:
        schema_path = os.path.join(REPO_DIR, "dbs", db_name, "head_schema", "schema.sql")
    if not os.path.isfile(schema_path):
        print(f"  WARN: schema file not found: {schema_path}")
        return
    with open(schema_path) as f:
        sql = f.read()
    expected = set(re.findall(r'CREATE\s+TABLE\s+(\w+)', sql, re.IGNORECASE))
    if not expected:
        return
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.isfile(db_path):
        conn = sqlite3.connect(db_path)
        actual = set(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
        conn.close()
        missing = expected - actual
        if not missing:
            return
        print(f"  {db_name}: missing tables {missing}, recreating db")
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(sql)
    conn.close()
    print(f"  {db_name}: schema applied from {schema_path}")

# ── synthetic fixtures ────────────────────────────────────────

CHAPTERS = ["ch01_intro", "ch02_journey", "ch03_climax"]
PAGES_PER_CHAPTER = 4
EVENT_TYPES = ["read_start", "read_end", "pause", "resume", "bookmark"]
INTERACTION_TYPES = ["tap", "swipe", "long_press", "double_tap"]
LABELS = ["bubble", "title", "sfx", "narration"]
SETTING_KEYS = ["theme", "font_size", "tts_enabled", "language"]
SENDERS = ["user", "assistant"]

def _rand_device():
    return "".join(random.choices(string.hexdigits[:16], k=16)).lower()

def _page_id(chapter, n):
    return f"{chapter}_p{n:02d}"

def _image_id(chapter, page_n, img_n):
    return f"{chapter}_p{page_n:02d}_img{img_n:02d}"

def build_payload(device_id=None, user_id=None, n_each=5, seed=None):
    """Build a UnifiedPayload v3 with ~n_each rows per table.

    The payload is deliberately self-consistent: every page_id / image_id
    used in an event row is also referenced via denormalized chapter_name /
    page_title, so the worker's catalog upsert has enough info to seed
    chapters/pages/images before FK-constrained inserts.
    """
    if seed is not None:
        random.seed(seed)
    device_id = device_id or _rand_device()
    now = int(time.time() * 1000)

    def _pick_page():
        ch = random.choice(CHAPTERS)
        pn = random.randint(1, PAGES_PER_CHAPTER)
        return ch, pn, _page_id(ch, pn)

    session_events = []
    for i in range(n_each):
        ch, pn, pid = _pick_page()
        session_events.append({
            "local_id": i + 1,
            "event_type": random.choice(EVENT_TYPES),
            "timestamp": now + i * 1000,
            "duration_ms": random.randint(100, 5000),
            "chapter_name": ch,
            "page_id": pid,
            "page_title": f"Page {pn} of {ch}",
            "synced": False,
        })

    annotation_records = []
    for i in range(n_each):
        ch, pn, pid = _pick_page()
        iid = _image_id(ch, pn, random.randint(1, 3))
        annotation_records.append({
            "local_id": i + 1,
            "image_id": iid,
            "box_index": i,
            "box_x": round(random.uniform(0.05, 0.7), 3),
            "box_y": round(random.uniform(0.05, 0.7), 3),
            "box_width": round(random.uniform(0.1, 0.3), 3),
            "box_height": round(random.uniform(0.05, 0.2), 3),
            "label": random.choice(LABELS),
            "timestamp": now + i * 1000,
            "tap_x": round(random.uniform(0.1, 0.9), 3),
            "tap_y": round(random.uniform(0.1, 0.9), 3),
            "region_type": "BUBBLE",
            "parent_bubble_index": None,
            "token_index": None,
            "synced": False,
        })

    chat_messages = [
        {
            "local_id": i + 1,
            "sender": random.choice(SENDERS),
            "text": f"synthetic message {i}",
            "timestamp": now + i * 500,
            "synced": False,
        }
        for i in range(n_each)
    ]

    page_interactions = []
    for i in range(n_each):
        ch, pn, pid = _pick_page()
        page_interactions.append({
            "local_id": i + 1,
            "interaction_type": random.choice(INTERACTION_TYPES),
            "timestamp": now + i * 750,
            "chapter_name": ch,
            "page_id": pid,
            "normalized_x": round(random.uniform(0, 1), 3),
            "normalized_y": round(random.uniform(0, 1), 3),
            "hit_result": random.choice(["bubble_hit", "miss", "token_hit"]),
            "synced": False,
        })

    app_launch_records = []
    for i in range(n_each):
        ch, pn, pid = _pick_page()
        app_launch_records.append({
            "local_id": i + 1,
            "package_name": "pl.czak.learnlauncher",
            "timestamp": now + i * 60000,
            "current_chapter": ch,
            "current_page_id": pid,
            "synced": False,
        })

    settings_changes = [
        {
            "local_id": i + 1,
            "setting_key": random.choice(SETTING_KEYS),
            "old_value": "v0",
            "new_value": f"v{i + 1}",
            "timestamp": now + i * 2000,
            "synced": False,
        }
        for i in range(n_each)
    ]

    region_translations = []
    seen = set()
    for i in range(n_each):
        ch, pn, _ = _pick_page()
        iid = _image_id(ch, pn, random.randint(1, 3))
        bidx = random.randint(0, 5)
        rid = f"{iid}_{bidx}"
        if rid in seen:
            continue
        seen.add(rid)
        region_translations.append({
            "id": rid,
            "image_id": iid,
            "bubble_index": bidx,
            "original_text": "こんにちは",
            "meaning_translation": "Hello",
            "literal_translation": "good day",
            "source_language": "ja",
            "target_language": "en",
        })

    return {
        "schema_version": 3,
        "export_timestamp": now,
        "app_version": "1.0-dummy",
        "device_id": device_id,
        "user_id": user_id,
        "mode": "export",
        "tables": {
            "session_events": session_events,
            "annotation_records": annotation_records,
            "chat_messages": chat_messages,
            "page_interactions": page_interactions,
            "app_launch_records": app_launch_records,
            "settings_changes": settings_changes,
            "region_translations": region_translations,
        },
    }

def submit_via_queue(payload):
    job = {"task": "ingest_unified_payload", "db": "app7", **payload}
    resp = client.submit(job)
    jid = resp.get("id")
    print(f"  submitted job #{jid}")
    # poll for completion
    deadline = time.time() + 10
    while time.time() < deadline:
        r = client.status(jid)
        if r.get("status") == "done":
            return r.get("result", {})
        time.sleep(0.1)
    raise TimeoutError(f"job {jid} not done within 10s")

def run_locally(payload):
    """Invoke the worker handler in-process against the local app7.db.

    Useful when the TCP queue server is not running.
    """
    from workers.app7 import worker  # noqa: E402
    job = {"task": "ingest_unified_payload", "db": "app7", **payload}
    return worker._ingest_unified_payload(job)

if __name__ == "__main__":
    mode = "queue"
    n = 5
    args = sys.argv[1:]
    if args and args[0] == "local":
        mode = "local"
        args = args[1:]
    if args:
        n = int(args[0])

    print(f"Ensuring app7 schema ({DBS['app7']})...")
    _ensure_schema("app7")

    payload = build_payload(n_each=n, seed=42)
    print(f"Built payload: {sum(len(v) for v in payload['tables'].values())} rows across "
          f"{len(payload['tables'])} tables, device_id={payload['device_id']}")

    if mode == "queue":
        result = submit_via_queue(payload)
    else:
        result = run_locally(payload)

    print(f"Result: {json.dumps(result, indent=2)}")

    # Sanity-check row counts directly from the DB
    conn = sqlite3.connect(DBS["app7"])
    for t in ["chapters", "pages", "images", "ingest_batches",
              "session_events", "annotation_records", "chat_messages",
              "page_interactions", "app_launch_records", "settings_changes",
              "region_translations"]:
        (cnt,) = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
        print(f"  {t:22s}  {cnt}")
    conn.close()
