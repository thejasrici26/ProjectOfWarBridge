import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from db_backup import (
    backup_database,
    cleanup_backups,
    restore_database,
    verify_backup_restore,
)


class DatabaseBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.live = self.root / "warbridge.db"
        with closing(sqlite3.connect(self.live)) as connection:
            connection.execute("CREATE TABLE examples(value TEXT NOT NULL)")
            connection.execute("INSERT INTO examples(value) VALUES('before')")
            connection.commit()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _value(self, path):
        with closing(sqlite3.connect(path)) as connection:
            return connection.execute("SELECT value FROM examples").fetchone()[0]

    def test_backup_verifies_integrity_and_generates_timestamped_name(self):
        backup_directory = self.root / "backups"
        with patch.dict(os.environ, {"WARBRIDGE_BACKUP_DIR": str(backup_directory)}):
            backup = backup_database(self.live)

        self.assertRegex(
            backup.name,
            r"^warbridge-backup-\d{8}T\d{6}Z(?:-\d{2})?\.sqlite3$",
        )
        self.assertTrue(verify_backup_restore(backup))
        self.assertEqual(self._value(backup), "before")

    def test_cli_uses_backup_environment_and_writes_logs(self):
        backup_directory = self.root / "configured-backups"
        environment = os.environ.copy()
        for key in (
            "WARBRIDGE_DEVELOPMENT_DATABASE_URL",
            "WARBRIDGE_TEST_DATABASE_URL",
            "WARBRIDGE_DATABASE_URL",
            "DATABASE_URL",
        ):
            environment.pop(key, None)
        environment.update(
            WARBRIDGE_ENV="development",
            WARBRIDGE_DB=str(self.live),
            WARBRIDGE_BACKUP_DIR=str(backup_directory),
            WARBRIDGE_BACKUP_ENCRYPTION_KEY="MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
            WARBRIDGE_BACKUP_RETENTION_DAYS="30",
            WARBRIDGE_BACKUP_RETENTION_COUNT="14",
            WARBRIDGE_LOG_LEVEL="INFO",
        )
        result = subprocess.run(
            [sys.executable, "db_backup.py", "backup", "--encrypt"],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        backup = Path(result.stdout.strip())
        self.assertTrue(backup.is_file())
        self.assertTrue(backup.name.endswith(".sqlite3.enc"))
        log_path = backup_directory / "warbridge-backup.log"
        self.assertIn("Backup created and verified", log_path.read_text())

    def test_encrypted_backup_verifies_and_restores_with_safety_copy(self):
        key = os.urandom(32)
        backup = backup_database(
            self.live,
            self.root / "warbridge-backup-encrypted.sqlite3.enc",
            encryption_key=key,
        )
        self.assertTrue(verify_backup_restore(backup, encryption_key=key))
        with backup.open("rb") as backup_file:
            self.assertNotEqual(backup_file.read(16), b"SQLite format 3\x00")

        with closing(sqlite3.connect(self.live)) as connection:
            connection.execute("UPDATE examples SET value='after'")
            connection.commit()
        restored, safety_copy = restore_database(
            backup,
            self.live,
            confirm=True,
            encryption_key=key,
        )
        self.assertEqual(restored, self.live.resolve())
        self.assertTrue(safety_copy and safety_copy.is_file())
        self.assertEqual(self._value(self.live), "before")
        self.assertEqual(self._value(safety_copy), "after")

    def test_corrupted_encrypted_backup_fails_verification(self):
        backup = backup_database(
            self.live,
            self.root / "corrupted.sqlite3.enc",
            encryption_key=os.urandom(32),
        )
        contents = bytearray(backup.read_bytes())
        contents[-1] ^= 0x01
        backup.write_bytes(contents)

        with self.assertRaisesRegex(ValueError, "authentication failed"):
            verify_backup_restore(backup, encryption_key=os.urandom(32))

    def test_corrupted_backup_and_failed_restore_leave_live_database_unchanged(self):
        corrupted = self.root / "corrupted.sqlite3"
        corrupted.write_bytes(b"not a SQLite database")
        with self.assertRaises(sqlite3.DatabaseError):
            verify_backup_restore(corrupted)
        with self.assertRaises(sqlite3.DatabaseError):
            restore_database(corrupted, self.live, confirm=True)
        self.assertEqual(self._value(self.live), "before")
        self.assertEqual(list(self.root.glob("warbridge.db.pre-restore-*")), [])

    def test_restore_requires_confirmation_and_prevents_live_path_overwrite(self):
        backup = backup_database(self.live, self.root / "backup.sqlite3")
        with self.assertRaisesRegex(PermissionError, "explicit confirmation"):
            restore_database(backup, self.live)
        with self.assertRaisesRegex(ValueError, "differ from the live database"):
            backup_database(self.live, self.live)
        with self.assertRaisesRegex(ValueError, "differ from the live database"):
            restore_database(self.live, self.live, confirm=True)
        self.assertEqual(self._value(self.live), "before")

    def test_restore_cli_requires_confirmation(self):
        backup = backup_database(self.live, self.root / "backup.sqlite3")
        environment = os.environ.copy()
        for key in (
            "WARBRIDGE_DEVELOPMENT_DATABASE_URL",
            "WARBRIDGE_TEST_DATABASE_URL",
            "WARBRIDGE_DATABASE_URL",
            "DATABASE_URL",
        ):
            environment.pop(key, None)
        environment.update(WARBRIDGE_ENV="development", WARBRIDGE_DB=str(self.live))
        result = subprocess.run(
            [
                sys.executable,
                "db_backup.py",
                "--database",
                str(self.live),
                "restore",
                "--input",
                str(backup),
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("restore requires --confirm-restore", result.stderr)
        self.assertEqual(self._value(self.live), "before")

    def test_backup_refuses_to_overwrite_existing_destination(self):
        destination = self.root / "already-there.sqlite3"
        destination.write_bytes(b"preserve me")
        with self.assertRaises(FileExistsError):
            backup_database(self.live, destination)
        self.assertEqual(destination.read_bytes(), b"preserve me")

    def test_retention_keeps_recent_and_configured_number_of_old_backups(self):
        now = datetime.now(timezone.utc)
        old = self.root / "warbridge-backup-old.sqlite3"
        middle = self.root / "warbridge-backup-middle.sqlite3.enc"
        newest = self.root / "warbridge-backup-newest.sqlite3"
        unrelated = self.root / "not-a-warbridge-backup.sqlite3"
        for path in (old, middle, newest, unrelated):
            path.write_bytes(b"placeholder")
        os.utime(old, (now.timestamp() - 90 * 86400,) * 2)
        os.utime(middle, (now.timestamp() - 60 * 86400,) * 2)
        os.utime(newest, (now.timestamp() - 45 * 86400,) * 2)

        deleted = cleanup_backups(
            self.root,
            retention_days=30,
            retention_count=1,
            now=now,
        )

        self.assertEqual(set(deleted), {old.resolve(), middle.resolve()})
        self.assertTrue(newest.exists())
        self.assertTrue(unrelated.exists())

    def test_retention_rejects_configuration_that_would_delete_every_backup(self):
        with self.assertRaisesRegex(ValueError, "At least one"):
            cleanup_backups(self.root, retention_days=0, retention_count=0)


if __name__ == "__main__":
    unittest.main()
