import os
import sqlite3

DB_PATH = os.environ.get("DATABASE_PATH", "database.db")


def delete_duplicate_rows(conn, table, key_columns):
    key_expr = ", ".join(key_columns)
    deleted = conn.execute(
        f"""
        DELETE FROM {table}
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM {table}
            GROUP BY {key_expr}
        )
        """
    ).rowcount
    return deleted


def keep_singleton(conn, table):
    row = conn.execute(f"SELECT MIN(id) FROM {table}").fetchone()
    if not row or row[0] is None:
        return 0
    return conn.execute(f"DELETE FROM {table} WHERE id <> ?", (row[0],)).rowcount


def cleanup():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")

    deleted = {}
    deleted["movies"] = delete_duplicate_rows(conn, "movies", ["title"])
    deleted["subscription_plans"] = delete_duplicate_rows(conn, "subscription_plans", ["name"])
    deleted["social_media"] = delete_duplicate_rows(conn, "social_media", ["platform", "url"])
    deleted["contact_info"] = delete_duplicate_rows(conn, "contact_info", ["type", "label", "value"])
    deleted["payment_info"] = delete_duplicate_rows(conn, "payment_info", ["payment_method", "account_number", "bank_name"])
    deleted["about_us"] = keep_singleton(conn, "about_us")
    deleted["website_settings"] = keep_singleton(conn, "website_settings")

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    if os.path.exists("movies.db.merged.bak"):
        os.makedirs("db_backups", exist_ok=True)
        destination = os.path.join("db_backups", "movies.db.merged.bak")
        if os.path.exists(destination):
            os.remove(destination)
        os.replace("movies.db.merged.bak", destination)

    print("Duplicate cleanup complete.")
    for table, count in deleted.items():
        print(f"{table}: removed {count} duplicate rows")


if __name__ == "__main__":
    cleanup()
