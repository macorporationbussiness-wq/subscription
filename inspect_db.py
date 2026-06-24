import os
import sqlite3

DB_PATH = os.environ.get("DATABASE_PATH", "database.db")
LEGACY_DB_PATH = "movies.db"

for db in [DB_PATH, LEGACY_DB_PATH]:
    print(f"\nDB: {db} exists={os.path.exists(db)} size={os.path.getsize(db) if os.path.exists(db) else 0}")
    if not os.path.exists(db):
        continue

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()

    for table in tables:
        name = table["name"]
        columns = [column["name"] for column in conn.execute(f"PRAGMA table_info({name})")]
        count = conn.execute(f"SELECT COUNT(*) AS count FROM {name}").fetchone()["count"]
        print(f"  {name}: {count} rows | {', '.join(columns)}")

    conn.close()
