"""Dummy load generator — heavy on learning sessions, light on new users."""
import time, random, string, client

def rand_name():
    return "".join(random.choices(string.ascii_lowercase, k=6))

def rand_email():
    return f"{rand_name()}@example.com"

TOPICS = ["kanji-n5", "kanji-n4", "grammar-particles", "grammar-verbs",
          "vocab-food", "vocab-travel", "reading-manga", "listening-anime",
          "hiragana", "katakana", "pitch-accent", "keigo"]

SETUP_JOBS = [
    ("main", "CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"),
    ("main", "CREATE TABLE IF NOT EXISTS learning_sessions(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), topic TEXT, started_at DATETIME DEFAULT CURRENT_TIMESTAMP, ended_at DATETIME, status TEXT DEFAULT 'active')"),
    ("logs", "CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, type TEXT, msg TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)"),
]

# Weighted job pool: ~70% sessions, ~10% users, ~20% queries
def random_job(user_ids):
    r = random.random()

    if r < 0.000001 or not user_ids:
        # 1 in a million — new user (or forced if none exist)
        name = rand_name()
        return "new_user", client.query("main",
            "INSERT INTO users(name, email) VALUES(?, ?)", [name, rand_email()])

    elif r < 0.90:
        # 90% — start a session
        uid = random.choice(user_ids)
        topic = random.choice(TOPICS)
        return "start_session", client.query("main",
            "INSERT INTO learning_sessions(user_id, topic) VALUES(?, ?)", [uid, topic])

    elif r < 0.94:
        # 4% — end a random active session
        uid = random.choice(user_ids)
        return "end_session", client.query("main",
            "UPDATE learning_sessions SET ended_at=CURRENT_TIMESTAMP, status='completed' "
            "WHERE id=(SELECT id FROM learning_sessions WHERE user_id=? AND status='active' ORDER BY RANDOM() LIMIT 1)",
            [uid])

    elif r < 0.96:
        # 2% — query sessions
        return "query", random.choice([
            lambda: client.query("main", "SELECT u.name, COUNT(ls.id) AS sessions FROM users u LEFT JOIN learning_sessions ls ON ls.user_id=u.id GROUP BY u.id ORDER BY sessions DESC LIMIT 5"),
            lambda: client.query("main", "SELECT topic, COUNT(*) AS n FROM learning_sessions GROUP BY topic ORDER BY n DESC"),
            lambda: client.query("main", "SELECT status, COUNT(*) AS n FROM learning_sessions GROUP BY status"),
            lambda: client.query("main", "SELECT COUNT(DISTINCT user_id) AS active_learners FROM learning_sessions WHERE status='active'"),
        ])()

    elif r < 0.98:
        # 2% — query logs
        return "query", random.choice([
            lambda: client.query("logs", "SELECT type, COUNT(*) AS n FROM events GROUP BY type ORDER BY n DESC"),
            lambda: client.query("logs", "SELECT * FROM events ORDER BY id DESC LIMIT 5"),
        ])()

    else:
        # 2% — log event or ping
        if random.random() < 0.5:
            uid = random.choice(user_ids)
            etype = random.choice(["page_view", "quiz_answer", "annotation", "replay"])
            return "log_event", client.query("logs",
                "INSERT INTO events(type, msg) VALUES(?, ?)",
                [etype, f"user {uid} did {etype} on {random.choice(TOPICS)}"])
        else:
            return "ping", client.ping()

if __name__ == "__main__":
    import sys
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 0.5
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    seed_users = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    # setup tables
    print("Setting up tables...")
    for db, sql in SETUP_JOBS:
        resp = client.query(db, sql)
        print(f"  {db}: {resp}")

    # seed initial users
    print(f"\nSeeding {seed_users} users...")
    user_ids = []
    for _ in range(seed_users):
        resp = client.query("main", "INSERT INTO users(name, email) VALUES(?, ?)",
                            [rand_name(), rand_email()])
        jid = resp.get("id", "?")
        print(f"  job #{jid}")
    # wait a bit for users to be created, then fetch IDs
    time.sleep(2)
    # We don't have the actual IDs yet (async), so we'll use a range
    user_ids = list(range(1, seed_users + 1))

    i = 0
    print(f"\nSubmitting jobs every {delay}s (Ctrl-C to stop)")
    print(f"  mix: ~5% new users, ~60% sessions, ~20% queries, ~10% logs, ~5% ping\n")
    try:
        while count == 0 or i < count:
            label, resp = random_job(user_ids)
            i += 1
            jid = resp.get("id", "?")
            print(f"  [{i:>4}] {label:>15}  job #{jid}")

            # track new user IDs (approximate — assumes sequential)
            if label == "new_user":
                user_ids.append(max(user_ids) + 1 if user_ids else 1)

            time.sleep(delay)
    except KeyboardInterrupt:
        print(f"\nStopped after {i} jobs.")
        print("\nQueue status:")
        print(client.ls())
