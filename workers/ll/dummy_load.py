"""Dummy load for ll (comic reader) — simulates realistic reading sessions.

Hierarchy exercised:
  learner → app_session → comic_session → page_session
    ├─ page_interaction  (next/prev/jump)
    └─ bubble_session
         ├─ bubble_annotation
         └─ word_interaction

Usage: python dummy_load.py [delay] [count] [seed_learners]
"""
import time, random, string, json, sys, os, re, sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import client

REPO_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

def _parse_dbs():
    raw = os.environ.get("QUEUE_DBS", "")
    if raw:
        return dict(pair.split("=", 1) for pair in raw.split(","))
    return {"ll": "/var/lib/myapp/ll.db"}

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
        print(f"  WARN: no CREATE TABLE found in {schema_path}")
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

# ── seed data ───────────────────────────────────────────────────

LANG_PAIRS = [("en", "ja"), ("en", "de"), ("en", "fr"), ("en", "es"),
              ("de", "en"), ("pt", "en"), ("zh", "en"), ("hi", "en")]

COMICS = [
    ("one-piece-ch1",    "One Piece Ch.1",    "ja", 3, 24),
    ("naruto-ch1",       "Naruto Ch.1",       "ja", 2, 18),
    ("asterix-gaul",     "Asterix the Gaul",  "fr", 2, 44),
    ("maus-vol1",        "Maus Vol.1",        "en", 4, 36),
    ("dragonball-ch1",   "Dragon Ball Ch.1",  "ja", 1, 14),
    ("tintin-tibet",     "Tintin in Tibet",   "fr", 3, 62),
    ("berserk-ch1",      "Berserk Ch.1",      "ja", 5, 20),
    ("corto-maltese",    "Corto Maltese",     "it", 4, 48),
]

ANNOTATIONS = [
    ("hard",             "Hard",              "🔴", 1),
    ("funny",            "Funny",             "😂", 2),
    ("unknown_grammar",  "Unknown Grammar",   "📐", 3),
    ("cultural_ref",     "Cultural Reference", "🌍", 4),
    ("review_later",     "Review Later",      "🔁", 5),
    ("slang",            "Slang",             "💬", 6),
    ("new_vocab",        "New Vocabulary",    "📖", 7),
    ("idiomatic",        "Idiomatic",         "🧩", 8),
]

BUBBLE_TEXTS = [
    ("What are you doing here?!", "Qu'est-ce que tu fais ici?!"),
    ("I will become the Pirate King!", "海賊王に俺はなる！"),
    ("Run! They're coming!", "Cours! Ils arrivent!"),
    ("I've been waiting for you.", "Je t'attendais."),
    ("This power... it's incredible!", "この力…すごい！"),
    ("Don't underestimate me.", "Unterschätze mich nicht."),
    ("Let's go home.", "Rentrons à la maison."),
    ("I won't give up!", "Ich gebe nicht auf!"),
    ("Watch out behind you!", "Attention derrière toi!"),
    ("The treasure is near.", "Le trésor est proche."),
]

WORD_POOL = [
    ("what",      "what",      "PRON", "was"),
    ("doing",     "do",        "VERB", "machen"),
    ("here",      "here",      "ADV",  "hier"),
    ("become",    "become",    "VERB", "werden"),
    ("pirate",    "pirate",    "NOUN", "Pirat"),
    ("king",      "king",      "NOUN", "König"),
    ("run",       "run",       "VERB", "laufen"),
    ("power",     "power",     "NOUN", "Kraft"),
    ("incredible","incredible","ADJ",  "unglaublich"),
    ("waiting",   "wait",      "VERB", "warten"),
    ("treasure",  "treasure",  "NOUN", "Schatz"),
    ("home",      "home",      "NOUN", "Zuhause"),
    ("behind",    "behind",    "PREP", "hinter"),
    ("give",      "give",      "VERB", "geben"),
    ("watch",     "watch",     "VERB", "aufpassen"),
]

APP_ACTIONS = ["open_settings", "open_library", "open_vocab_list",
               "open_stats", "toggle_theme", "change_profile"]

PAGE_ACTIONS = ["next", "prev", "pinch_zoom", "double_tap_zoom", "scroll"]

TRIGGERS = ["tap", "long_press", "auto_focus"]
WORD_INTERACTIONS = ["tap", "long_press", "double_tap"]

# ── helpers ─────────────────────────────────────────────────────

def rand_device():
    return "".join(random.choices(string.hexdigits[:16], k=16))

def rand_name():
    return "".join(random.choices(string.ascii_lowercase, k=6))

def rand_bbox():
    x, y = round(random.uniform(0.05, 0.8), 3), round(random.uniform(0.05, 0.8), 3)
    w, h = round(random.uniform(0.05, 0.3), 3), round(random.uniform(0.03, 0.15), 3)
    return x, y, w, h

def _local_conn():
    """Direct connection to local ll.db for seeding."""
    c = sqlite3.connect(DBS["ll"])
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c

def submit(task, **kw):
    kw["task"] = task
    kw["db"] = "ll"
    return client.submit(kw)

def wait_for_result(job_id, timeout=10, poll_interval=0.1):
    """Poll until job completes and return its handler result dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.status(job_id)
        if resp.get("status") == "done":
            return resp.get("result", {})
        time.sleep(poll_interval)
    raise TimeoutError(f"job {job_id} not done within {timeout}s")

def load_content_ids():
    """Query real IDs and relationship maps from local ll.db."""
    conn = _local_conn()
    content = {
        "comic_ids":      [r[0] for r in conn.execute("SELECT id FROM comics").fetchall()],
        "page_ids":       [r[0] for r in conn.execute("SELECT id FROM pages").fetchall()],
        "bubble_ids":     [r[0] for r in conn.execute("SELECT id FROM bubbles").fetchall()],
        "word_ids":       [r[0] for r in conn.execute("SELECT id FROM words").fetchall()],
        "annotation_ids": [r[0] for r in conn.execute("SELECT id FROM annotation_options").fetchall()],
        "pages_by_comic":  {},
        "bubbles_by_page": {},
        "words_by_bubble": {},
    }
    for cid, pid in conn.execute("SELECT comic_id, id FROM pages"):
        content["pages_by_comic"].setdefault(cid, []).append(pid)
    for pid, bid in conn.execute("SELECT page_id, id FROM bubbles"):
        content["bubbles_by_page"].setdefault(pid, []).append(bid)
    for bid, wid in conn.execute("SELECT bubble_id, id FROM words"):
        content["words_by_bubble"].setdefault(bid, []).append(wid)
    conn.close()
    return content

# ── seeding (direct local db writes) ───────────────────────────

def seed_all(n_learners):
    """Seed all reference data and learners directly into local ll.db."""
    conn = _local_conn()
    now = int(time.time() * 1000)

    # annotations
    for slug, label, icon, sort in ANNOTATIONS:
        conn.execute("INSERT OR IGNORE INTO annotation_options(slug, label, icon, sort_order) "
                     "VALUES(?, ?, ?, ?)", [slug, label, icon, sort])
    print(f"  annotations: {len(ANNOTATIONS)}")

    # comics
    for slug, title, lang, diff, npages in COMICS:
        conn.execute("INSERT OR IGNORE INTO comics(slug, title, lang, difficulty, total_pages, created_at) "
                     "VALUES(?, ?, ?, ?, ?, ?)", [slug, title, lang, diff, npages, now])
    print(f"  comics: {len(COMICS)}")

    # pages
    page_count = 0
    comic_rows = conn.execute("SELECT id, total_pages FROM comics ORDER BY id").fetchall()
    for cid, npages in comic_rows:
        for pn in range(1, npages + 1):
            conn.execute("INSERT OR IGNORE INTO pages(comic_id, page_number, image_uri) VALUES(?, ?, ?)",
                         [cid, pn, f"assets/comic_{cid}/page_{pn:03d}.webp"])
            page_count += 1
    print(f"  pages: {page_count}")

    # bubbles + words
    page_ids = [r[0] for r in conn.execute("SELECT id FROM pages").fetchall()]
    bubble_count = 0
    word_count = 0
    for page_id in page_ids[:50]:
        n_bubbles = random.randint(2, 6)
        for bi in range(n_bubbles):
            text, trans = random.choice(BUBBLE_TEXTS)
            bx, by, bw, bh = rand_bbox()
            conn.execute("INSERT OR IGNORE INTO bubbles(page_id, bubble_index, bbox_x, bbox_y, bbox_w, bbox_h, "
                         "full_text, translation) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                         [page_id, bi, bx, by, bw, bh, text, trans])
            bubble_count += 1
    conn.commit()
    # now insert words referencing actual bubble IDs
    bubble_rows = conn.execute("SELECT id FROM bubbles").fetchall()
    for (bid,) in bubble_rows:
        words_in = random.sample(WORD_POOL, k=min(random.randint(2, 5), len(WORD_POOL)))
        for wi, (surface, lemma, pos, transl) in enumerate(words_in):
            wx, wy, ww, wh = rand_bbox()
            conn.execute("INSERT OR IGNORE INTO words(bubble_id, word_index, surface_form, lemma, pos, "
                         "translation, bbox_x, bbox_y, bbox_w, bbox_h) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         [bid, wi, surface, lemma, pos, transl, wx, wy, ww, wh])
            word_count += 1
    print(f"  bubbles: {bubble_count}, words: {word_count}")

    # learners
    learner_ids = []
    for _ in range(n_learners):
        native, target = random.choice(LANG_PAIRS)
        cur = conn.execute(
            "INSERT INTO learners(device_id, display_name, native_lang, target_lang, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            [rand_device(), rand_name(), native, target, now, now])
        learner_ids.append(cur.lastrowid)
    print(f"  learners: {len(learner_ids)}")

    conn.commit()
    conn.close()
    return learner_ids

# ── state tracking (real DB IDs) ───────────────────────────────

class State:
    def __init__(self, learner_ids, content):
        self.learner_ids = learner_ids
        self.content = content              # from load_content_ids()
        self.active_app_sessions = {}       # learner_id -> app_session_id (real)
        self.active_comic_sessions = {}     # app_session_id -> (comic_session_id, comic_id) (real)
        self.active_page_sessions = {}      # comic_session_id -> (page_session_id, page_id) (real)
        self.active_bubble_sessions = {}    # page_session_id -> (bubble_session_id, bubble_id) (real)

    def _cascade_close(self, app_session_id):
        """Remove all child sessions under an app session."""
        cs = self.active_comic_sessions.pop(app_session_id, None)
        if cs:
            csid, cid = cs
            ps = self.active_page_sessions.pop(csid, None)
            if ps:
                psid, pid = ps
                self.active_bubble_sessions.pop(psid, None)

# ── job generators ──────────────────────────────────────────────

def random_job(state):
    C = state.content
    r = random.random()
    lid = random.choice(state.learner_ids)

    # ── 15% — app session start/end ──
    if r < 0.15:
        if lid not in state.active_app_sessions:
            resp = submit("app_session_start", learner_id=lid)
            result = wait_for_result(resp["id"])
            state.active_app_sessions[lid] = result["app_session_id"]
            return "app_start", resp
        else:
            sid = state.active_app_sessions.pop(lid)
            state._cascade_close(sid)
            return "app_end", submit("app_session_end",
                                     learner_id=lid, app_session_id=sid,
                                     reason=random.choice(["background", "killed", "logout"]))

    elif r < 0.20:
        # ── 5% — app interaction ──
        if lid in state.active_app_sessions:
            return "app_interact", submit("app_interact",
                                          learner_id=lid,
                                          app_session_id=state.active_app_sessions[lid],
                                          action=random.choice(APP_ACTIONS))

    # ── 25% — comic session start ──
    if r < 0.45:
        if lid in state.active_app_sessions:
            asid = state.active_app_sessions[lid]
            if asid not in state.active_comic_sessions:
                cid = random.choice(C["comic_ids"])
                resp = submit("comic_session_start",
                              learner_id=lid, app_session_id=asid, comic_id=cid)
                result = wait_for_result(resp["id"])
                csid = result["comic_session_id"]
                state.active_comic_sessions[asid] = (csid, cid)
                return "comic_start", resp

    # ── 25% — page session start / page interaction ──
    if r < 0.70:
        if lid in state.active_app_sessions:
            asid = state.active_app_sessions[lid]
            if asid in state.active_comic_sessions:
                csid, cid = state.active_comic_sessions[asid]
                if csid not in state.active_page_sessions:
                    pages = C["pages_by_comic"].get(cid, C["page_ids"])
                    page_id = random.choice(pages)
                    resp = submit("page_session_start",
                                  learner_id=lid, comic_session_id=csid, page_id=page_id)
                    result = wait_for_result(resp["id"])
                    psid = result["page_session_id"]
                    state.active_page_sessions[csid] = (psid, page_id)
                    return "page_start", resp
                else:
                    psid, cur_page = state.active_page_sessions[csid]
                    action = random.choice(PAGE_ACTIONS)
                    pages = C["pages_by_comic"].get(cid, C["page_ids"])
                    to_page = random.choice(pages)
                    return "page_interact", submit("page_interact",
                                                   learner_id=lid, page_session_id=psid,
                                                   action=action, to_page_id=to_page)

    # ── 20% — bubble session ──
    if r < 0.90:
        if lid in state.active_app_sessions:
            asid = state.active_app_sessions[lid]
            if asid in state.active_comic_sessions:
                csid, cid = state.active_comic_sessions[asid]
                if csid in state.active_page_sessions:
                    psid, page_id = state.active_page_sessions[csid]
                    if psid not in state.active_bubble_sessions:
                        bubbles = C["bubbles_by_page"].get(page_id, C["bubble_ids"])
                        if not bubbles:
                            bubbles = C["bubble_ids"]
                        bubble_id = random.choice(bubbles)
                        resp = submit("bubble_session_start",
                                      learner_id=lid, page_session_id=psid,
                                      bubble_id=bubble_id,
                                      trigger=random.choice(TRIGGERS),
                                      showed_translation=random.randint(0, 1),
                                      played_audio=random.randint(0, 1))
                        result = wait_for_result(resp["id"])
                        bsid = result["bubble_session_id"]
                        state.active_bubble_sessions[psid] = (bsid, bubble_id)
                        return "bubble_start", resp
                    else:
                        bsid, bubble_id = state.active_bubble_sessions[psid]
                        if random.random() < 0.4:
                            ann_id = random.choice(C["annotation_ids"])
                            return "annotate", submit("bubble_annotate",
                                                      learner_id=lid,
                                                      bubble_session_id=bsid,
                                                      annotation_id=ann_id)
                        else:
                            words = C["words_by_bubble"].get(bubble_id, C["word_ids"])
                            if not words:
                                words = C["word_ids"]
                            word_id = random.choice(words)
                            return "word_tap", submit("word_interact",
                                                      learner_id=lid,
                                                      bubble_session_id=bsid,
                                                      word_id=word_id,
                                                      interaction=random.choice(WORD_INTERACTIONS),
                                                      showed_translation=random.randint(0, 1),
                                                      played_audio=random.randint(0, 1),
                                                      added_to_vocab=1 if random.random() < 0.15 else 0)

    # ── 5% — close bubble session ──
    if r < 0.95:
        for psid, (bsid, bid) in list(state.active_bubble_sessions.items()):
            state.active_bubble_sessions.pop(psid)
            return "bubble_end", submit("bubble_session_end",
                                        learner_id=lid, bubble_session_id=bsid,
                                        showed_translation=random.randint(0, 1),
                                        played_audio=random.randint(0, 1))

    # ── 3% — close page session ──
    if r < 0.98:
        for csid, (psid, pid) in list(state.active_page_sessions.items()):
            state.active_page_sessions.pop(csid)
            return "page_end", submit("page_session_end",
                                      learner_id=lid, page_session_id=psid,
                                      scroll_depth=round(random.uniform(0.3, 1.0), 2))

    # ── 2% — analytics queries ──
    return "query", random.choice([
        lambda: client.query("ll", "SELECT COUNT(*) AS n FROM events"),
        lambda: client.query("ll", "SELECT event_name, COUNT(*) AS n FROM events GROUP BY event_name ORDER BY n DESC LIMIT 10"),
        lambda: client.query("ll", "SELECT l.display_name, COUNT(e.id) AS events FROM learners l "
                  "LEFT JOIN events e ON e.learner_id=l.id GROUP BY l.id ORDER BY events DESC LIMIT 5"),
        lambda: client.query("ll", "SELECT entity_type, COUNT(*) AS n FROM events GROUP BY entity_type ORDER BY n DESC"),
        lambda: client.query("ll", "SELECT COUNT(DISTINCT learner_id) AS active FROM app_sessions WHERE ended_at IS NULL"),
    ])()

# ── main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    seed_n = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    print("Ensuring ll schema...")
    _ensure_schema("ll")

    print("Seeding local db...")
    learner_ids = seed_all(seed_n)

    print("Loading content IDs...")
    content = load_content_ids()
    print(f"  comics: {len(content['comic_ids'])}, pages: {len(content['page_ids'])}, "
          f"bubbles: {len(content['bubble_ids'])}, words: {len(content['word_ids'])}")

    state = State(learner_ids, content)
    i = 0
    print(f"\nSubmitting jobs every {delay}s (Ctrl-C to stop)")
    print(f"  hierarchy: app -> comic -> page -> bubble -> word/annotation\n")
    try:
        while count == 0 or i < count:
            try:
                label, resp = random_job(state)
            except TimeoutError as e:
                print(f"  [WARN] {e}")
                continue
            i += 1
            jid = resp.get("id", "?")
            print(f"  [{i:>4}] {label:>15}  job #{jid}")
            time.sleep(delay)
    except KeyboardInterrupt:
        print(f"\nStopped after {i} jobs.")
        print("\nQueue status:")
        print(client.ls())
