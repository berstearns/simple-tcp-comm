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

def q(sql, params=None):
    return client.query("ll", sql, params or [])

def submit(task, **kw):
    kw["task"] = task
    kw["db"] = "ll"
    return client.submit(kw)

# ── seeding ─────────────────────────────────────────────────────

def seed_comics():
    """Insert comic catalog."""
    now = int(time.time() * 1000)
    ids = []
    for slug, title, lang, diff, pages in COMICS:
        resp = q("INSERT OR IGNORE INTO comics(slug, title, lang, difficulty, total_pages, created_at) "
                 "VALUES(?, ?, ?, ?, ?, ?)", [slug, title, lang, diff, pages, now])
        ids.append(slug)
    return ids

def seed_pages(comic_ids):
    """Generate pages for each comic (fetch real comic IDs first)."""
    rows = q("SELECT id, total_pages FROM comics")
    if not rows.get("ok"):
        time.sleep(1)
        rows = client.status(rows["id"])
    comics = []
    resp = q("SELECT id, total_pages FROM comics")
    # we'll just insert pages optimistically
    for comic_idx, (slug, title, lang, diff, npages) in enumerate(COMICS):
        cid = comic_idx + 1  # approximate
        for pn in range(1, npages + 1):
            q("INSERT OR IGNORE INTO pages(comic_id, page_number, image_uri) VALUES(?, ?, ?)",
              [cid, pn, f"assets/{slug}/page_{pn:03d}.webp"])
        comics.append((cid, npages))
    return comics

def seed_bubbles_and_words():
    """Sprinkle bubbles and words onto pages."""
    resp = q("SELECT id FROM pages")
    # approximate: just do first 50 pages
    for page_id in range(1, 51):
        n_bubbles = random.randint(2, 6)
        for bi in range(n_bubbles):
            text, trans = random.choice(BUBBLE_TEXTS)
            bx, by, bw, bh = rand_bbox()
            q("INSERT OR IGNORE INTO bubbles(page_id, bubble_index, bbox_x, bbox_y, bbox_w, bbox_h, "
              "full_text, translation) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
              [page_id, bi, bx, by, bw, bh, text, trans])
            # words inside this bubble
            bubble_id_approx = (page_id - 1) * 6 + bi + 1
            words_in = random.sample(WORD_POOL, k=min(random.randint(2, 5), len(WORD_POOL)))
            for wi, (surface, lemma, pos, transl) in enumerate(words_in):
                wx, wy, ww, wh = rand_bbox()
                q("INSERT OR IGNORE INTO words(bubble_id, word_index, surface_form, lemma, pos, "
                  "translation, bbox_x, bbox_y, bbox_w, bbox_h) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  [bubble_id_approx, wi, surface, lemma, pos, transl, wx, wy, ww, wh])

def seed_annotations():
    """Insert fixed annotation options."""
    for slug, label, icon, sort in ANNOTATIONS:
        q("INSERT OR IGNORE INTO annotation_options(slug, label, icon, sort_order) "
          "VALUES(?, ?, ?, ?)", [slug, label, icon, sort])

def seed_learners(n):
    """Create n learners."""
    ids = []
    for _ in range(n):
        native, target = random.choice(LANG_PAIRS)
        resp = submit("create_learner",
                      device_id=rand_device(),
                      display_name=rand_name(),
                      native_lang=native,
                      target_lang=target)
        ids.append(resp.get("id", "?"))
        print(f"  seeded learner job #{ids[-1]}")
    time.sleep(2)
    return list(range(1, n + 1))

# ── state tracking (in-memory, approximate) ─────────────────────

class State:
    def __init__(self, learner_ids):
        self.learner_ids = learner_ids
        self.active_app_sessions = {}      # learner_id -> app_session_id
        self.active_comic_sessions = {}    # app_session_id -> (comic_session_id, comic_id)
        self.active_page_sessions = {}     # comic_session_id -> (page_session_id, page_id)
        self.active_bubble_sessions = {}   # page_session_id -> (bubble_session_id, bubble_id)
        self.next_ids = {
            "app_session": 1, "comic_session": 1, "page_session": 1,
            "bubble_session": 1, "annotation": 1, "word_int": 1,
        }

    def _inc(self, k):
        v = self.next_ids[k]
        self.next_ids[k] += 1
        return v

# ── job generators ──────────────────────────────────────────────

def random_job(state):
    r = random.random()
    lid = random.choice(state.learner_ids)

    # ── 25% — app session start/end ──
    if r < 0.15:
        if lid not in state.active_app_sessions:
            sid = state._inc("app_session")
            state.active_app_sessions[lid] = sid
            return "app_start", submit("app_session_start", learner_id=lid)
        else:
            sid = state.active_app_sessions.pop(lid)
            # cascade close
            state.active_comic_sessions.pop(sid, None)
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
        # fallthrough to comic session

    # ── 25% — comic session start ──
    if r < 0.45:
        if lid in state.active_app_sessions:
            asid = state.active_app_sessions[lid]
            if asid not in state.active_comic_sessions:
                csid = state._inc("comic_session")
                cid = random.randint(1, len(COMICS))
                state.active_comic_sessions[asid] = (csid, cid)
                return "comic_start", submit("comic_session_start",
                                             learner_id=lid, app_session_id=asid, comic_id=cid)

    # ── 25% — page session start / page interaction ──
    if r < 0.70:
        if lid in state.active_app_sessions:
            asid = state.active_app_sessions[lid]
            if asid in state.active_comic_sessions:
                csid, cid = state.active_comic_sessions[asid]
                if csid not in state.active_page_sessions:
                    # start page session
                    psid = state._inc("page_session")
                    page_id = random.randint(1, 50)
                    state.active_page_sessions[csid] = (psid, page_id)
                    return "page_start", submit("page_session_start",
                                                learner_id=lid, comic_session_id=csid, page_id=page_id)
                else:
                    # page interaction (navigate)
                    psid, cur_page = state.active_page_sessions[csid]
                    action = random.choice(PAGE_ACTIONS)
                    to_page = cur_page + 1 if action == "next" else (cur_page - 1 if action == "prev" else cur_page)
                    to_page = max(1, min(50, to_page))
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
                        # open bubble
                        bsid = state._inc("bubble_session")
                        bubble_id = random.randint(1, 300)
                        state.active_bubble_sessions[psid] = (bsid, bubble_id)
                        return "bubble_start", submit("bubble_session_start",
                                                      learner_id=lid, page_session_id=psid,
                                                      bubble_id=bubble_id,
                                                      trigger=random.choice(TRIGGERS),
                                                      showed_translation=random.randint(0, 1),
                                                      played_audio=random.randint(0, 1))
                    else:
                        bsid, bubble_id = state.active_bubble_sessions[psid]
                        # 50% annotate, 50% word tap
                        if random.random() < 0.4:
                            ann_id = random.randint(1, len(ANNOTATIONS))
                            return "annotate", submit("bubble_annotate",
                                                      learner_id=lid,
                                                      bubble_session_id=bsid,
                                                      annotation_id=ann_id)
                        else:
                            word_id = random.randint(1, 500)
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
        lambda: q("SELECT COUNT(*) AS n FROM events"),
        lambda: q("SELECT event_name, COUNT(*) AS n FROM events GROUP BY event_name ORDER BY n DESC LIMIT 10"),
        lambda: q("SELECT l.display_name, COUNT(e.id) AS events FROM learners l "
                  "LEFT JOIN events e ON e.learner_id=l.id GROUP BY l.id ORDER BY events DESC LIMIT 5"),
        lambda: q("SELECT entity_type, COUNT(*) AS n FROM events GROUP BY entity_type ORDER BY n DESC"),
        lambda: q("SELECT COUNT(DISTINCT learner_id) AS active FROM app_sessions WHERE ended_at IS NULL"),
    ])()

# ── main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    seed_n = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    print("Ensuring ll schema...")
    _ensure_schema("ll")

    print("Seeding annotation options...")
    seed_annotations()

    print("Seeding comics catalog...")
    seed_comics()

    print("Seeding pages, bubbles, words...")
    seed_pages([])
    seed_bubbles_and_words()

    print(f"\nSeeding {seed_n} learners...")
    learner_ids = seed_learners(seed_n)

    state = State(learner_ids)
    i = 0
    print(f"\nSubmitting jobs every {delay}s (Ctrl-C to stop)")
    print(f"  hierarchy: app → comic → page → bubble → word/annotation\n")
    try:
        while count == 0 or i < count:
            label, resp = random_job(state)
            i += 1
            jid = resp.get("id", "?")
            print(f"  [{i:>4}] {label:>15}  job #{jid}")
            time.sleep(delay)
    except KeyboardInterrupt:
        print(f"\nStopped after {i} jobs.")
        print("\nQueue status:")
        print(client.ls())
