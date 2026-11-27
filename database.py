import logging
import math
import os
import re
import sqlite3
import threading
from pathlib import Path

import psycopg
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


logger = logging.getLogger("warbridge.database")


class DatabaseIntegrityError(Exception):
    pass


def _log_database_error(error, dialect, operation, level=logging.ERROR):
    logger.log(
        level,
        "Database operation failed",
        extra={
            "event": "database_error",
            "db_dialect": dialect,
            "operation": operation,
            "error_type": type(error).__name__,
        },
    )


class CursorAdapter:
    def __init__(self, cursor, dialect, returning_id=False):
        self.cursor = cursor
        self.dialect = dialect
        self.returning_id = returning_id
        self.cached_row = None
        self.row_cached = False

    @property
    def rowcount(self):
        return self.cursor.rowcount

    @property
    def lastrowid(self):
        if self.dialect == "sqlite":
            return self.cursor.lastrowid
        if not self.returning_id:
            return None
        if not self.row_cached:
            self.cached_row = self.cursor.fetchone()
            self.row_cached = True
        return self.cached_row["id"] if self.cached_row else None

    def fetchone(self):
        if self.row_cached:
            self.row_cached = False
            row = self.cached_row
            self.cached_row = None
            return row
        return self.cursor.fetchone()

    def fetchall(self):
        if self.row_cached:
            self.row_cached = False
            row = self.cached_row
            self.cached_row = None
            return ([row] if row is not None else []) + self.cursor.fetchall()
        return self.cursor.fetchall()

    def __iter__(self):
        if self.row_cached:
            self.row_cached = False
            row = self.cached_row
            self.cached_row = None
            if row is not None:
                yield row
        yield from self.cursor


class Database:
    AUTO_ID_TABLES = {
        "users",
        "shelters",
        "accommodations",
        "services",
        "alerts",
        "help_requests",
        "reports",
        "ratings",
        "audit_log",
        "rate_limit_events",
        "emergency_notifications",
    }

    def __init__(self, connection, dialect, pool=None):
        self.connection = connection
        self.dialect = dialect
        self.pool = pool

    def execute(self, sql, params=()):
        if self.dialect == "sqlite":
            try:
                return CursorAdapter(
                    self.connection.execute(sql, params),
                    dialect="sqlite",
                )
            except sqlite3.IntegrityError as error:
                _log_database_error(error, self.dialect, "execute", logging.WARNING)
                raise DatabaseIntegrityError(str(error)) from error
            except sqlite3.Error as error:
                _log_database_error(error, self.dialect, "execute")
                raise

        statement = sql.strip()
        if statement.upper() == "BEGIN IMMEDIATE":
            if self.connection.info.transaction_status == TransactionStatus.IDLE:
                self.connection.execute("BEGIN")
            cursor = self.connection.cursor()
            try:
                cursor.execute(
                    """LOCK TABLE users, shelters, accommodations, services, alerts,
                       help_requests, reports, ratings, audit_log, rate_limit_events,
                       emergency_notifications,
                       schema_migrations IN SHARE ROW EXCLUSIVE MODE"""
                )
            except psycopg.Error as error:
                cursor.close()
                _log_database_error(error, self.dialect, "transaction_lock")
                raise
            return CursorAdapter(cursor, dialect="postgresql")

        match = re.match(r"INSERT\s+INTO\s+([a-z_]+)", statement, re.IGNORECASE)
        returning_id = bool(
            match
            and match.group(1).lower() in self.AUTO_ID_TABLES
            and "RETURNING" not in statement.upper()
        )
        if returning_id:
            statement = statement.rstrip(";") + " RETURNING id"
        statement = statement.replace("?", "%s")
        cursor = self.connection.cursor()
        try:
            cursor.execute(statement, params)
        except psycopg.IntegrityError as error:
            cursor.close()
            _log_database_error(error, self.dialect, "execute", logging.WARNING)
            raise DatabaseIntegrityError(str(error)) from error
        except psycopg.Error as error:
            cursor.close()
            _log_database_error(error, self.dialect, "execute")
            raise
        return CursorAdapter(
            cursor,
            dialect="postgresql",
            returning_id=returning_id,
        )

    def executescript(self, script):
        if self.dialect == "sqlite":
            self.connection.executescript(script)
            return
        script = re.sub(
            r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
            "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
            script,
            flags=re.IGNORECASE,
        )
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def table_columns(self, table):
        if self.dialect == "sqlite":
            return {
                row["name"]
                for row in self.execute(f"PRAGMA table_info({table})").fetchall()
            }
        rows = self.execute(
            """SELECT column_name AS name FROM information_schema.columns
               WHERE table_schema=current_schema() AND table_name=?""",
            (table,),
        ).fetchall()
        return {row["name"] for row in rows}

    @property
    def in_transaction(self):
        if self.dialect == "sqlite":
            return self.connection.in_transaction
        return self.connection.info.transaction_status != TransactionStatus.IDLE

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        if self.dialect == "sqlite":
            self.connection.close()
            return
        if self.in_transaction:
            self.connection.rollback()
        self.pool.putconn(self.connection)


def _positive_int(name, default):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} must be a positive integer") from error
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def _positive_float(name, default):
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} must be a positive number") from error
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError(f"{name} must be a positive number")
    return value


def _normalize_postgres_url(url):
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


APP_ENV = os.getenv("WARBRIDGE_ENV", "production").strip().lower()
if APP_ENV == "test":
    DATABASE_URL = os.getenv("WARBRIDGE_TEST_DATABASE_URL")
    if DATABASE_URL and any(
        configured_url
        and _normalize_postgres_url(configured_url)
        == _normalize_postgres_url(DATABASE_URL)
        for configured_url in (
            os.getenv("WARBRIDGE_DATABASE_URL"),
            os.getenv("DATABASE_URL"),
        )
    ):
        raise RuntimeError(
            "WARBRIDGE_TEST_DATABASE_URL must be separate from the production database URL"
        )
elif APP_ENV == "development":
    DATABASE_URL = os.getenv("WARBRIDGE_DEVELOPMENT_DATABASE_URL") or os.getenv(
        "WARBRIDGE_DATABASE_URL"
    ) or os.getenv("DATABASE_URL")
else:
    DATABASE_URL = os.getenv("WARBRIDGE_DATABASE_URL") or os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASE_URL = _normalize_postgres_url(DATABASE_URL)
    if not DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("Database URL must use PostgreSQL")

DATABASE_POOL_SIZE = _positive_int("WARBRIDGE_DB_POOL_SIZE", 5)
DATABASE_CONNECTION_TIMEOUT = _positive_float("WARBRIDGE_DB_CONNECTION_TIMEOUT", 10)
SQLITE_DATABASE = Path(
    os.getenv("WARBRIDGE_DB", Path(__file__).resolve().parent / "warbridge.db")
)

_pool = None
_pool_lock = threading.Lock()


def _postgres_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    conninfo=DATABASE_URL,
                    min_size=1,
                    max_size=DATABASE_POOL_SIZE,
                    timeout=DATABASE_CONNECTION_TIMEOUT,
                    kwargs={
                        "row_factory": dict_row,
                        "connect_timeout": max(
                            1,
                            math.ceil(DATABASE_CONNECTION_TIMEOUT),
                        ),
                    },
                    open=False,
                )
                _pool.open(wait=False)
    return _pool


def connect_database():
    try:
        if DATABASE_URL:
            pool = _postgres_pool()
            connection = pool.getconn(timeout=DATABASE_CONNECTION_TIMEOUT)
            return Database(connection, "postgresql", pool)

        SQLITE_DATABASE.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            SQLITE_DATABASE,
            timeout=DATABASE_CONNECTION_TIMEOUT,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            f"PRAGMA busy_timeout = {int(DATABASE_CONNECTION_TIMEOUT * 1000)}"
        )
        return Database(connection, "sqlite")
    except Exception as error:
        _log_database_error(
            error,
            "postgresql" if DATABASE_URL else "sqlite",
            "connect",
        )
        raise
