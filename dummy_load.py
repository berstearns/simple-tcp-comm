"""Dummy load generator — keeps submitting INSERT + SELECT jobs."""
import time, random, string, client

def rand_name():
    return "".join(random.choices(string.ascii_lowercase, k=6))

def rand_email():
    return f"{rand_name()}@example.com"

# First, ensure tables exist on the worker's DBs
SETUP_JOBS = [
    ("main", "CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"),
    ("logs", "CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, type TEXT, msg TEXT, ts DATETIME DEFAULT CURRENT_TIMESTAMP)"),
]

# Mix of INSERTs and SELECTs
def random_job():
    return random.choice([
        # inserts
        lambda: client.query("main", "INSERT INTO users(name, email) VALUES(?, ?)", [rand_name(), rand_email()]),
        lambda: client.query("main", "INSERT INTO users(name, email) VALUES(?, ?)", [rand_name(), rand_email()]),
        lambda: client.query("logs", "INSERT INTO events(type, msg) VALUES(?, ?)", ["click", f"user did {rand_name()}"]),
        lambda: client.query("logs", "INSERT INTO events(type, msg) VALUES(?, ?)", ["error", f"failed: {rand_name()}"]),
        # selects
        lambda: client.query("main", "SELECT count(*) AS total FROM users"),
        lambda: client.query("main", "SELECT * FROM users ORDER BY id DESC LIMIT 3"),
        lambda: client.query("logs", "SELECT * FROM events ORDER BY id DESC LIMIT 5"),
        lambda: client.query("logs", "SELECT type, count(*) AS n FROM events GROUP BY type"),
        # other
        lambda: client.ping(),
        lambda: client.execute("date"),
    ])()

if __name__ == "__main__":
    import sys
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 0  # 0 = infinite

    # setup tables first
    print("Setting up tables...")
    for db, sql in SETUP_JOBS:
        resp = client.query(db, sql)
        print(f"  {db}: {resp}")

    i = 0
    print(f"\nSubmitting jobs every {delay}s (Ctrl-C to stop)")
    try:
        while count == 0 or i < count:
            resp = random_job()
            i += 1
            jid = resp.get("id", "?")
            print(f"  [{i:>4}] job #{jid}")
            time.sleep(delay)
    except KeyboardInterrupt:
        print(f"\nStopped after {i} jobs.")
        # show final counts
        print("\nQueue status:")
        print(client.ls())
