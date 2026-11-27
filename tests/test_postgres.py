import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg import sql as pgsql
from psycopg.rows import dict_row


class DatabaseSafetyTests(unittest.TestCase):
    def test_test_database_rejects_production_url_alias(self):
        env = os.environ.copy()
        for key in (
            "WARBRIDGE_TEST_DATABASE_URL",
            "WARBRIDGE_DATABASE_URL",
            "DATABASE_URL",
        ):
            env.pop(key, None)
        env.update(
            WARBRIDGE_ENV="test",
            WARBRIDGE_TEST_DATABASE_URL="postgresql://user@localhost/warbridge",
            WARBRIDGE_DATABASE_URL="postgres://user@localhost/warbridge",
        )
        result = subprocess.run(
            [sys.executable, "-c", "import database"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be separate", result.stderr)


@unittest.skipUnless(
    os.getenv("WARBRIDGE_TEST_DATABASE_URL"),
    "Set WARBRIDGE_TEST_DATABASE_URL to run PostgreSQL integration tests",
)
class PostgreSQLIntegrationTests(unittest.TestCase):
    def test_schema_migrations_indexes_and_existing_rows(self):
        os.environ["WARBRIDGE_ENV"] = "test"
        from app import app, get_db, init_db, utcnow

        with app.app_context():
            init_db()
            db = get_db()
            self.assertEqual(db.dialect, "postgresql")
            suffix = uuid.uuid4().hex
            cursor = db.execute(
                """INSERT INTO users(name,email,password_hash,role,verified,created_at)
                   VALUES(?,?,?,?,1,?)""",
                (
                    "PostgreSQL integration",
                    f"{suffix}@example.test",
                    "unused",
                    "DISPLACED",
                    utcnow(),
                ),
            )
            user_id = cursor.lastrowid
            db.commit()

            init_db()
            self.assertEqual(
                get_db().execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()["id"],
                user_id,
            )
            self.assertEqual(
                [
                    row["version"]
                    for row in get_db().execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    ).fetchall()
                ],
                [1, 2, 3, 4],
            )
            indexes = {
                row["indexname"]
                for row in get_db().execute(
                    "SELECT indexname FROM pg_indexes WHERE schemaname=current_schema()"
                ).fetchall()
            }
            self.assertTrue(
                {
                    "idx_users_email",
                    "idx_help_requests_status",
                    "idx_help_requests_sos_status",
                    "idx_shelters_verification_block",
                    "idx_accommodations_verification_block",
                    "idx_services_verification_block",
                    "idx_alerts_expires_at",
                    "idx_audit_log_created_at",
                    "idx_notifications_request_status",
                }.issubset(indexes)
            )
            get_db().commit()

    def test_foreign_keys_are_declared_and_enforced(self):
        os.environ["WARBRIDGE_ENV"] = "test"
        from app import app, get_db, init_db, utcnow
        from database import DatabaseIntegrityError

        with app.app_context():
            init_db()
            db = get_db()
            foreign_keys = {
                (row["table_name"], row["column_name"], row["foreign_table_name"])
                for row in db.execute(
                    """SELECT tc.table_name,kcu.column_name,
                              ccu.table_name AS foreign_table_name
                       FROM information_schema.table_constraints tc
                       JOIN information_schema.key_column_usage kcu
                         ON tc.constraint_catalog=kcu.constraint_catalog
                        AND tc.constraint_schema=kcu.constraint_schema
                        AND tc.constraint_name=kcu.constraint_name
                        AND tc.table_name=kcu.table_name
                       JOIN information_schema.constraint_column_usage ccu
                         ON tc.constraint_catalog=ccu.constraint_catalog
                        AND tc.constraint_schema=ccu.constraint_schema
                        AND tc.constraint_name=ccu.constraint_name
                       WHERE tc.constraint_type='FOREIGN KEY'
                         AND tc.table_schema=current_schema()"""
                ).fetchall()
            }
            self.assertTrue(
                {
                    ("shelters", "ngo_id", "users"),
                    ("accommodations", "host_id", "users"),
                    ("help_requests", "requester_id", "users"),
                    ("help_requests", "shelter_id", "shelters"),
                    ("help_requests", "accommodation_id", "accommodations"),
                    ("emergency_notifications", "request_id", "help_requests"),
                }.issubset(foreign_keys)
            )
            with self.assertRaises(DatabaseIntegrityError):
                db.execute(
                    """INSERT INTO shelters(
                           ngo_id,name,city,area,updated_at
                       ) VALUES(0,'Invalid FK','Test City','Test Area',?)""",
                    (utcnow(),),
                )
            db.rollback()

    def test_concurrent_acceptance_cannot_overbook_postgresql_capacity(self):
        os.environ["WARBRIDGE_ENV"] = "test"
        from app import app, get_db, init_db, utcnow

        app.config.update(TESTING=True)
        suffix = uuid.uuid4().hex
        with app.app_context():
            init_db()
            db = get_db()
            self.assertEqual(db.dialect, "postgresql")
            host = db.execute(
                """INSERT INTO users(name,email,password_hash,role,verified,created_at)
                   VALUES(?,?,?,?,1,?)""",
                (f"PG host {suffix}", f"pg-host-{suffix}@example.test", "unused", "HOST", utcnow()),
            ).lastrowid
            requesters = [
                db.execute(
                    """INSERT INTO users(name,email,password_hash,role,verified,created_at)
                       VALUES(?,?,?,?,1,?)""",
                    (
                        f"PG requester {suffix}-{index}",
                        f"pg-requester-{suffix}-{index}@example.test",
                        "unused",
                        "DISPLACED",
                        utcnow(),
                    ),
                ).lastrowid
                for index in range(2)
            ]
            accommodation_id = db.execute(
                """INSERT INTO accommodations(
                       host_id,city,area,rooms,rooms_available,verified,updated_at
                   ) VALUES(?,'Test City','Test Area',1,1,1,?)""",
                (host, utcnow()),
            ).lastrowid
            request_ids = [
                db.execute(
                    """INSERT INTO help_requests(
                           requester_id,accommodation_id,type,status,updated_at,created_at
                       ) VALUES(?,?,'accommodation','Pending',?,?)""",
                    (requester, accommodation_id, utcnow(), utcnow()),
                ).lastrowid
                for requester in requesters
            ]
            db.commit()

        barrier = threading.Barrier(2)

        def accept(request_id):
            client = app.test_client()
            token = secrets.token_urlsafe(32)
            with client.session_transaction() as session:
                session["user_id"] = host
                session["csrf_token"] = token
            barrier.wait(timeout=10)
            return client.post(
                f"/api/requests/{request_id}/accept",
                headers={"X-CSRF-Token": token},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            status_codes = list(pool.map(accept, request_ids))
        self.assertCountEqual(status_codes, [200, 409])

        with app.app_context():
            db = get_db()
            self.assertEqual(
                db.execute(
                    "SELECT rooms_available FROM accommodations WHERE id=?",
                    (accommodation_id,),
                ).fetchone()["rooms_available"],
                0,
            )
            request_statuses = db.execute(
                "SELECT status FROM help_requests WHERE id IN (?,?)",
                request_ids,
            ).fetchall()
            self.assertCountEqual(
                [row["status"] for row in request_statuses],
                ["Accepted", "Pending"],
            )
            db.commit()

    def test_sqlite_to_postgresql_migration_preserves_rows_and_capacity(self):
        database_url = os.environ["WARBRIDGE_TEST_DATABASE_URL"]
        schema = f"warbridge_migration_{uuid.uuid4().hex}"
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(
                pgsql.SQL("CREATE SCHEMA {}").format(pgsql.Identifier(schema))
            )

        parsed_url = urlsplit(database_url)
        query = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
        query["options"] = f"-c search_path={schema}"
        target_url = urlunsplit(
            parsed_url._replace(query=urlencode(query, quote_via=quote))
        )

        try:
            with tempfile.TemporaryDirectory() as directory:
                source_path = Path(directory) / "legacy.sqlite3"
                source = sqlite3.connect(source_path)
                try:
                    source.executescript(
                        """
                        CREATE TABLE users (
                            id INTEGER PRIMARY KEY,
                            name TEXT NOT NULL,
                            email TEXT UNIQUE NOT NULL,
                            password_hash TEXT NOT NULL,
                            role TEXT NOT NULL,
                            gender TEXT,
                            verified INTEGER NOT NULL DEFAULT 0,
                            blocked INTEGER NOT NULL DEFAULT 0,
                            created_at TEXT NOT NULL
                        );
                        CREATE TABLE accommodations (
                            id INTEGER PRIMARY KEY,
                            host_id INTEGER NOT NULL,
                            city TEXT NOT NULL,
                            area TEXT NOT NULL,
                            address TEXT,
                            rooms INTEGER NOT NULL,
                            women_only INTEGER NOT NULL DEFAULT 0,
                            description TEXT,
                            verified INTEGER NOT NULL DEFAULT 0,
                            blocked INTEGER NOT NULL DEFAULT 0,
                            closed INTEGER NOT NULL DEFAULT 0,
                            updated_at TEXT NOT NULL
                        );
                        CREATE TABLE help_requests (
                            id INTEGER PRIMARY KEY,
                            requester_id INTEGER,
                            accommodation_id INTEGER,
                            type TEXT NOT NULL,
                            status TEXT NOT NULL,
                            is_sos INTEGER NOT NULL DEFAULT 0,
                            updated_at TEXT NOT NULL,
                            created_at TEXT NOT NULL
                        );
                        """
                    )
                    source.executemany(
                        """INSERT INTO users(
                               id,name,email,password_hash,role,verified,created_at
                           ) VALUES(?,?,?,?,?,?,?)""",
                        [
                            (21, "Legacy host", "legacy-host@example.test", "unused", "HOST", 1, "2024-01-01"),
                            (22, "Legacy requester", "legacy-requester@example.test", "unused", "DISPLACED", 0, "2024-01-02"),
                        ],
                    )
                    source.execute(
                        """INSERT INTO accommodations(
                               id,host_id,city,area,rooms,verified,updated_at
                           ) VALUES(31,21,'Test City','Test Area',3,1,'2024-01-03')"""
                    )
                    source.execute(
                        """INSERT INTO help_requests(
                               id,requester_id,accommodation_id,type,status,updated_at,created_at
                           ) VALUES(41,22,31,'accommodation','Pending','2024-01-04','2024-01-04')"""
                    )
                    source.commit()
                finally:
                    source.close()

                env = os.environ.copy()
                env.update(
                    WARBRIDGE_ENV="development",
                    WARBRIDGE_DEVELOPMENT_DATABASE_URL=target_url,
                    SECRET_KEY=secrets.token_hex(32),
                )
                for name in (
                    "WARBRIDGE_DATABASE_URL",
                    "DATABASE_URL",
                    "WARBRIDGE_TEST_DATABASE_URL",
                ):
                    env.pop(name, None)
                result = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).resolve().parents[1] / "migrate_sqlite_to_postgres.py"),
                        "--source",
                        str(source_path),
                    ],
                    cwd=Path(__file__).resolve().parents[1],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            with psycopg.connect(target_url, row_factory=dict_row) as connection:
                accommodation = connection.execute(
                    "SELECT host_id,rooms,rooms_available FROM accommodations WHERE id=31"
                ).fetchone()
                self.assertEqual(
                    dict(accommodation),
                    {"host_id": 21, "rooms": 3, "rooms_available": 3},
                )
                request_row = connection.execute(
                    """SELECT requester_id,accommodation_id,status
                       FROM help_requests WHERE id=41"""
                ).fetchone()
                self.assertEqual(
                    dict(request_row),
                    {"requester_id": 22, "accommodation_id": 31, "status": "Pending"},
                )
                next_user = connection.execute(
                    """INSERT INTO users(name,email,password_hash,role,created_at)
                       VALUES('Sequence check','sequence@example.test','unused','DISPLACED','2024-01-05')
                       RETURNING id"""
                ).fetchone()
                self.assertGreater(next_user["id"], 22)
        finally:
            with psycopg.connect(database_url, autocommit=True) as connection:
                connection.execute(
                    pgsql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        pgsql.Identifier(schema)
                    )
                )


if __name__ == "__main__":
    unittest.main()
