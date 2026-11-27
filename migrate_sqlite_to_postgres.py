import argparse
import os
import sqlite3
from pathlib import Path

from app import app, get_db, init_db


TABLES = (
    "users",
    "shelters",
    "accommodations",
    "services",
    "alerts",
    "help_requests",
    "emergency_notifications",
    "reports",
    "ratings",
    "audit_log",
    "rate_limit_events",
    "demo_seed",
)


def migrate(source_path):
    source_path = Path(source_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite source database does not exist: {source_path}")

    with app.app_context():
        db = get_db()
        if db.dialect != "postgresql":
            raise RuntimeError(
                "Set WARBRIDGE_DATABASE_URL or WARBRIDGE_DEVELOPMENT_DATABASE_URL "
                "to a PostgreSQL target before running this migration"
            )

        saved_admin_settings = {
            key: os.environ.pop(key)
            for key in ("WARBRIDGE_ADMIN_EMAIL", "WARBRIDGE_ADMIN_PASSWORD")
            if key in os.environ
        }
        try:
            init_db()
        finally:
            os.environ.update(saved_admin_settings)

        db.execute(
            """CREATE TABLE IF NOT EXISTS demo_seed (
                   id INTEGER PRIMARY KEY CHECK(id=1),
                   seeded_at TEXT NOT NULL
               )"""
        )
        source = sqlite3.connect(source_path)
        source.row_factory = sqlite3.Row
        try:
            source_tables = {
                row["name"]
                for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            db.execute("BEGIN IMMEDIATE")
            for table in TABLES:
                if db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]:
                    raise RuntimeError(
                        f"PostgreSQL target table {table!r} is not empty; "
                        "migration requires a fresh target"
                    )

            migrated = {}
            for table in TABLES:
                if table not in source_tables:
                    migrated[table] = 0
                    continue
                source_columns = [
                    row["name"]
                    for row in source.execute(f"PRAGMA table_info({table})")
                ]
                target_columns = db.table_columns(table)
                source_data_columns = [
                    name for name in source_columns if name in target_columns
                ]
                columns = list(source_data_columns)
                derive_available_rooms = (
                    table == "accommodations" and "rooms_available" not in columns
                )
                if derive_available_rooms:
                    columns.append("rooms_available")
                rows = source.execute(
                    f"SELECT {','.join(source_data_columns)} FROM {table}"
                ).fetchall()
                for row in rows:
                    values = list(row)
                    if derive_available_rooms:
                        values.append(row["rooms"])
                    placeholders = ",".join("?" for _ in columns)
                    column_list = ",".join(columns)
                    cursor = db.execute(
                        f"INSERT INTO {table}({column_list}) "
                        f"VALUES({placeholders}) RETURNING id",
                        values,
                    )
                    cursor.fetchone()
                migrated[table] = len(rows)

            for table in TABLES:
                if table == "demo_seed":
                    continue
                db.execute(
                    f"""SELECT setval(
                            pg_get_serial_sequence(?, 'id'),
                            COALESCE(MAX(id), 1),
                            COUNT(*) > 0
                        ) FROM {table}""",
                    (table,),
                ).fetchone()
            db.commit()
            return migrated
        except Exception:
            db.rollback()
            raise
        finally:
            source.close()


def main():
    parser = argparse.ArgumentParser(
        description="Copy WarBridge data from a SQLite database to an empty PostgreSQL database."
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Path to the existing SQLite database file",
    )
    args = parser.parse_args()
    migrated = migrate(args.source)
    print("SQLite data migration completed:")
    for table, count in migrated.items():
        print(f"  {table}: {count} rows")


if __name__ == "__main__":
    main()
