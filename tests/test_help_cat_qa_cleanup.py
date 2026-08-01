import sqlite3
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.help_cat_qa_cleanup import build_cleanup_preview, cleanup
from scripts.help_cat_qa_seed import BATCH, PREFIX, expected_entities, qa_accounts


class HelpCatQaCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.database = self.root / "help-cat.db"
        self.storage = self.root / "uploads"
        self.storage.mkdir()
        self.manifest = self._manifest()
        self._create_database()
        (self.storage / "qa-photo.jpg").write_bytes(b"qa")
        (self.storage / "real-photo.jpg").write_bytes(b"real")

    def tearDown(self):
        self.tmp.cleanup()

    def _manifest(self):
        entities = expected_entities()
        return {
            "batch": BATCH,
            "prefix": PREFIX,
            "users": {
                key: {"id": "u-" + key, "username": value["username"], "role": value["role"]}
                for key, value in qa_accounts().items()
            },
            "communities": {key: dict(value, id="c-" + key) for key, value in entities["communities"].items()},
            "cats": {key: dict(value, id="cat-" + key) for key, value in entities["cats"].items()},
            "tasks": {key: dict(value, id="task-" + key) for key, value in entities["tasks"].items()},
            "media": {"id": "media-qa", "object_key": "qa-photo.jpg"},
            "audit_actions": ["ROLE_CHANGE", "CREATE", "UPLOAD", "REVIEW", "VISIBILITY", "ARCHIVE", "CLAIM"],
            "super_admin": {"count": 1, "username": "zack", "role": "SUPER_ADMIN"},
        }

    def _create_database(self):
        schema = """
        CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT, role TEXT);
        CREATE TABLE sessions(token TEXT PRIMARY KEY, user_id TEXT);
        CREATE TABLE daily_cat_quotas(user_id TEXT, quota_date TEXT);
        CREATE TABLE communities(id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE cats(id TEXT PRIMARY KEY, nickname TEXT, community_id TEXT, photo_asset_id TEXT, created_by TEXT);
        CREATE TABLE tasks(id TEXT PRIMARY KEY, title TEXT, community_id TEXT, created_by TEXT, claimed_by TEXT);
        CREATE TABLE media_assets(id TEXT PRIMARY KEY, object_key TEXT, created_by TEXT);
        CREATE TABLE audit_logs(id TEXT PRIMARY KEY, actor_id TEXT, entity_id TEXT);
        """
        with sqlite3.connect(self.database) as connection:
            connection.executescript(schema)
            users = [(item["id"], item["username"], item["role"]) for item in self.manifest["users"].values()]
            connection.executemany("INSERT INTO users VALUES (?, ?, ?)", users + [("u-real", "real_user", "USER")])
            connection.executemany("INSERT INTO sessions VALUES (?, ?)", [("s-admin", "u-admin"), ("s-a", "u-user_a"), ("s-b", "u-user_b"), ("s-real", "u-real")])
            connection.executemany("INSERT INTO daily_cat_quotas VALUES (?, ?)", [("u-user_a", "2026-08-01"), ("u-real", "2026-08-01")])
            connection.executemany(
                "INSERT INTO communities VALUES (?, ?)",
                [(item["id"], item["name"]) for item in self.manifest["communities"].values()] + [("c-real", "真实小区")],
            )
            connection.executemany(
                "INSERT INTO cats VALUES (?, ?, ?, ?, ?)",
                [(item["id"], item["name"], "c-active", "media-qa" if key == "admin_photo" else None, "u-admin") for key, item in self.manifest["cats"].items()]
                + [("cat-real", "真实猫咪", "c-real", "media-real", "u-real")],
            )
            connection.executemany(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?)",
                [(item["id"], item["name"], "c-active", "u-admin", "u-user_a" if key == "claimed" else None) for key, item in self.manifest["tasks"].items()]
                + [("task-real", "真实任务", "c-real", "u-real", None)],
            )
            connection.executemany("INSERT INTO media_assets VALUES (?, ?, ?)", [("media-qa", "qa-photo.jpg", "u-admin"), ("media-real", "real-photo.jpg", "u-real")])
            connection.executemany(
                "INSERT INTO audit_logs VALUES (?, ?, ?)",
                [("audit-role", "zack-id", "u-admin"), ("audit-cat", "u-admin", "cat-public"), ("audit-real", "u-real", "cat-real")],
            )
            connection.commit()

    def _count(self, table):
        with sqlite3.connect(self.database) as connection:
            return connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def test_dry_run_reports_exact_batch_without_changes(self):
        with sqlite3.connect(self.database) as connection:
            preview = build_cleanup_preview(connection, self.storage, self.manifest)
            result = cleanup(connection, self.storage, self.manifest, execute=False)
        self.assertEqual(result, preview)
        self.assertEqual(
            preview,
            {
                "audit_logs": 2,
                "sessions": 3,
                "daily_cat_quotas": 1,
                "tasks": 2,
                "cats": 6,
                "media_assets": 1,
                "communities": 4,
                "users": 3,
                "media_files": 1,
            },
        )
        self.assertEqual(self._count("users"), 4)
        self.assertTrue((self.storage / "qa-photo.jpg").is_file())

    def test_execute_removes_only_manifest_rows_and_media(self):
        with sqlite3.connect(self.database) as connection:
            cleanup(connection, self.storage, self.manifest, execute=True)
        for table in ("users", "sessions", "daily_cat_quotas", "communities", "cats", "tasks", "media_assets", "audit_logs"):
            self.assertEqual(self._count(table), 1, table)
        self.assertFalse((self.storage / "qa-photo.jpg").exists())
        self.assertTrue((self.storage / "real-photo.jpg").is_file())
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT username FROM users").fetchall(), [("real_user",)])

    def test_cleanup_script_runs_when_deployed_beside_seed_script(self):
        tools = self.root / "tools"
        tools.mkdir()
        project_root = Path(__file__).resolve().parents[1]
        shutil.copy2(project_root / "scripts" / "help_cat_qa_seed.py", tools / "help_cat_qa_seed.py")
        shutil.copy2(project_root / "scripts" / "help_cat_qa_cleanup.py", tools / "help_cat_qa_cleanup.py")
        result = subprocess.run(
            [sys.executable, str(tools / "help_cat_qa_cleanup.py"), "--help"],
            cwd=self.root,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
