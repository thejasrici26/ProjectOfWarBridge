import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEED_SCRIPT = ROOT / "seed_demo.py"


class DemoSeedTests(unittest.TestCase):
    def run_seed(self, database, environment="development"):
        env = os.environ.copy()
        env.update(
            WARBRIDGE_ENV=environment,
            WARBRIDGE_DB=str(database),
            SECRET_KEY="demo-seed-test-secret",
        )
        return subprocess.run(
            [sys.executable, str(SEED_SCRIPT)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_seed_creates_demo_workflows_once(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "demo.sqlite3"

            first = self.run_seed(database)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("Temporary demo password:", first.stdout)

            second = self.run_seed(database)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("already present", second.stdout)

            db = sqlite3.connect(database)
            try:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 5)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM shelters").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM accommodations").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM services").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM reports").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM help_requests").fetchone()[0], 4)
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM help_requests WHERE status='Completed'").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM help_requests WHERE is_sos=1 AND status='Pending'").fetchone()[0],
                    1,
                )
            finally:
                db.close()

    def test_seed_requires_explicit_development_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "should-not-exist.sqlite3"
            result = self.run_seed(database, environment="test")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("only be seeded", result.stderr)
            self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
