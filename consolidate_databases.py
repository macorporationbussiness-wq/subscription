import os
import shutil
import sqlite3
from datetime import datetime

MAIN_DB = "database.db"
OLD_DB = "movies.db"
BACKUP_DIR = "db_backups"

MOVIE_COLUMNS = [
    ("thumbnail", "TEXT"),
    ("banner_image", "TEXT"),
    ("description", "TEXT"),
    ("video_url", "TEXT"),
    ("trailer_url", "TEXT"),
    ("cast", "TEXT"),
    ("screenshots", "TEXT"),
    ("rating", "REAL DEFAULT 0.0"),
    ("featured", "INTEGER DEFAULT 0"),
    ("show_in_banner", "INTEGER DEFAULT 0"),
]

PLAN_COLUMNS = [
    ("max_users", "INTEGER DEFAULT 1"),
    ("duration_unit", "TEXT DEFAULT 'month'"),
    ("duration_value", "INTEGER DEFAULT 1"),
]

PAYMENT_COLUMNS = [
    ("payment_method", "TEXT"),
    ("bank_name", "TEXT"),
    ("account_number", "TEXT"),
    ("account_holder", "TEXT"),
    ("amount", "REAL"),
]

SUBSCRIPTION_COLUMNS = [
    ("start_date", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ("end_date", "TIMESTAMP"),
]


def backup_database(path):
    if not os.path.exists(path):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"{path}.{stamp}.bak")
    shutil.copy2(path, backup_path)
    return backup_path


def table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def column_names(conn, table):
    if not table_exists(conn, table):
        return []
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def add_missing_columns(conn, table, columns):
    existing = set(column_names(conn, table))
    for name, definition in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def ensure_schema(conn):
    conn.execute("PRAGMA foreign_keys = ON")
    with open("database.sql", "r", encoding="utf-8") as schema_file:
        conn.executescript(schema_file.read())

    add_missing_columns(conn, "movies", MOVIE_COLUMNS)
    add_missing_columns(conn, "subscription_plans", PLAN_COLUMNS)
    add_missing_columns(conn, "payments", PAYMENT_COLUMNS)
    add_missing_columns(conn, "subscriptions", SUBSCRIPTION_COLUMNS)
    conn.commit()


def merge_categories(conn):
    rows = conn.execute("SELECT name FROM old_db.categories").fetchall()
    for (name,) in rows:
        conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))


def merge_movies(conn):
    rows = conn.execute(
        """
        SELECT m.title, c.name AS category_name, m.thumbnail, m.banner_image, m.description,
               m.video_url, m.trailer_url, m.cast, m.screenshots, m.rating, m.featured, m.show_in_banner
        FROM old_db.movies m
        LEFT JOIN old_db.categories c ON c.id = m.category_id
        """
    ).fetchall()

    inserted = 0
    for row in rows:
        title = row["title"]
        exists = conn.execute("SELECT 1 FROM movies WHERE title = ?", (title,)).fetchone()
        if exists:
            continue

        category = conn.execute("SELECT id FROM categories WHERE name = ?", (row["category_name"],)).fetchone()
        category_id = category["id"] if category else None
        if category_id is None:
            fallback = conn.execute("SELECT id FROM categories ORDER BY id LIMIT 1").fetchone()
            category_id = fallback["id"] if fallback else 1

        conn.execute(
            """
            INSERT INTO movies (
                title, category_id, thumbnail, banner_image, description, video_url,
                trailer_url, cast, screenshots, rating, featured, show_in_banner
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                category_id,
                row["thumbnail"],
                row["banner_image"],
                row["description"],
                row["video_url"],
                row["trailer_url"],
                row["cast"],
                row["screenshots"],
                row["rating"] or 0,
                row["featured"] or 0,
                row["show_in_banner"] or 0,
            ),
        )
        inserted += 1
    return inserted


def merge_subscription_plans(conn):
    rows = conn.execute("SELECT * FROM old_db.subscription_plans").fetchall()
    inserted = 0
    for row in rows:
        exists = conn.execute("SELECT 1 FROM subscription_plans WHERE name = ?", (row["name"],)).fetchone()
        if exists:
            continue
        duration_months = row["duration_months"] or 1
        conn.execute(
            """
            INSERT INTO subscription_plans (
                name, duration_months, duration_unit, duration_value, price_pkr,
                discount_percentage, max_users, features, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["name"],
                duration_months,
                "month",
                duration_months,
                row["price_pkr"],
                row["discount_percentage"] or 0,
                1,
                row["features"],
                row["is_active"] if row["is_active"] is not None else 1,
                row["created_at"],
            ),
        )
        inserted += 1
    return inserted


def consolidate():
    main_backup = backup_database(MAIN_DB)
    old_backup = backup_database(OLD_DB)

    conn = sqlite3.connect(MAIN_DB)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    movie_count = 0
    plan_count = 0
    if os.path.exists(OLD_DB):
        conn.execute("ATTACH DATABASE ? AS old_db", (OLD_DB,))
        merge_categories(conn)
        movie_count = merge_movies(conn)
        plan_count = merge_subscription_plans(conn)
        conn.commit()
        conn.execute("DETACH DATABASE old_db")

        archived_old_db = f"{OLD_DB}.merged.bak"
        if os.path.exists(archived_old_db):
            os.remove(archived_old_db)
        os.replace(OLD_DB, archived_old_db)
    else:
        archived_old_db = None

    conn.close()
    print("Database consolidation complete.")
    print(f"Main backup: {main_backup}")
    print(f"Old database backup: {old_backup}")
    print(f"Archived old database: {archived_old_db}")
    print(f"Movies imported from old database: {movie_count}")
    print(f"Subscription plans imported from old database: {plan_count}")


if __name__ == "__main__":
    consolidate()
