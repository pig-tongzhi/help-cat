import json
import socket
import sqlite3
import stat
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

from server.helpcat.app import create_app
from scripts.help_cat_qa_cleanup import cleanup

from scripts.help_cat_qa_seed import (
    BATCH,
    PREFIX,
    SeedConfig,
    expected_entities,
    qa_accounts,
    seed_full_flow,
    validate_manifest,
)


class HelpCatQaSeedContractTests(unittest.TestCase):
    def test_accounts_and_entities_stay_inside_batch_namespace(self):
        accounts = qa_accounts()
        self.assertEqual(set(accounts), {"admin", "user_a", "user_b"})
        usernames = [item["username"] for item in accounts.values()]
        self.assertEqual(len(usernames), len(set(usernames)))
        self.assertTrue(all(name.endswith("_20260801") for name in usernames))

        entities = expected_entities()
        visible_names = [item["name"] for group in entities.values() for item in group.values()]
        self.assertTrue(visible_names)
        self.assertTrue(all(name.startswith(PREFIX) for name in visible_names))

    def test_expected_entities_cover_every_implemented_state(self):
        entities = expected_entities()
        self.assertEqual(
            {item["status"] for item in entities["communities"].values()},
            {"ACTIVE", "PENDING_REVIEW", "HIDDEN", "ARCHIVED"},
        )
        self.assertEqual(
            {(item["review_status"], item["visibility_status"]) for item in entities["cats"].values()},
            {
                ("PENDING_REVIEW", "ACTIVE"),
                ("APPROVED", "ACTIVE"),
                ("REJECTED", "ACTIVE"),
                ("APPROVED", "HIDDEN"),
                ("APPROVED", "ARCHIVED"),
            },
        )
        self.assertEqual(
            {item["status"] for item in entities["tasks"].values()},
            {"OPEN", "CLAIMED"},
        )

    def test_manifest_validation_requires_exact_batch_ids_and_unique_zack(self):
        entities = expected_entities()
        manifest = {
            "batch": BATCH,
            "prefix": PREFIX,
            "users": {
                key: {"id": "user-" + key, "username": value["username"], "role": value["role"]}
                for key, value in qa_accounts().items()
            },
            "communities": {
                key: dict(value, id="community-" + key) for key, value in entities["communities"].items()
            },
            "cats": {key: dict(value, id="cat-" + key) for key, value in entities["cats"].items()},
            "tasks": {key: dict(value, id="task-" + key) for key, value in entities["tasks"].items()},
            "media": {"id": "media-photo", "object_key": "qa-photo.jpg"},
            "audit_actions": ["ROLE_CHANGE", "CREATE", "UPLOAD", "REVIEW", "VISIBILITY", "ARCHIVE", "CLAIM"],
            "super_admin": {"count": 1, "username": "zack", "role": "SUPER_ADMIN"},
        }
        self.assertIs(validate_manifest(manifest), manifest)

        wrong_batch = dict(manifest, batch="QA-OTHER")
        with self.assertRaisesRegex(ValueError, "batch"):
            validate_manifest(wrong_batch)

        missing_id = dict(manifest)
        missing_id["cats"] = {key: dict(value) for key, value in manifest["cats"].items()}
        missing_id["cats"]["pending"].pop("id")
        with self.assertRaisesRegex(ValueError, "id"):
            validate_manifest(missing_id)

        wrong_super = dict(manifest, super_admin={"count": 2, "username": "zack", "role": "SUPER_ADMIN"})
        with self.assertRaisesRegex(ValueError, "super"):
            validate_manifest(wrong_super)


class HelpCatQaSeedIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.database = self.root / "help-cat.db"
        self.storage = self.root / "uploads"
        self.manifest = self.root / "QA-20260801-manifest.json"
        self.credentials = self.root / "QA-20260801-credentials.txt"
        self.port = self._free_port()
        app = create_app("sqlite:///" + str(self.database), self.storage)
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="critical", ws="none"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        self.base_url = "http://127.0.0.1:%d" % self.port
        self._wait_for_health()
        self._json("POST", "/api/v1/auth/register", {"username": "zack", "password": "zack-test-password"}, expected=201)
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE users SET role = 'SUPER_ADMIN' WHERE username = 'zack'")
            connection.commit()

    def tearDown(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    @staticmethod
    def _free_port():
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return listener.getsockname()[1]

    def _wait_for_health(self):
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                self._json("GET", "/api/v1/health", expected=200)
                return
            except Exception:
                time.sleep(0.05)
        self.fail("local Help Cat API did not start")

    def _json(self, method, path, payload=None, token=None, expected=200):
        headers = {}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = response.status
                body = json.load(response)
        except urllib.error.HTTPError as error:
            status = error.code
            body = json.load(error)
        self.assertEqual(status, expected, body)
        return body

    def test_seed_runs_real_api_and_refuses_duplicate_batch(self):
        config = SeedConfig(
            base_url=self.base_url,
            database=self.database,
            storage_root=self.storage,
            manifest=self.manifest,
            credentials=self.credentials,
        )
        passwords = {
            "admin": "qa-admin-test-password",
            "user_a": "qa-user-a-test-password",
            "user_b": "qa-user-b-test-password",
        }
        manifest = seed_full_flow(config, passwords)
        self.assertIs(validate_manifest(manifest), manifest)
        self.assertEqual(stat.S_IMODE(self.manifest.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.credentials.stat().st_mode), 0o600)

        public_communities = self._json("GET", "/api/v1/communities")["items"]
        self.assertEqual([item["name"] for item in public_communities if item["name"].startswith(PREFIX)], [PREFIX + "星河家园"])
        public_cats = self._json("GET", "/api/v1/cats")["items"]
        self.assertEqual(
            {item["nickname"] for item in public_cats if item["nickname"].startswith(PREFIX)},
            {PREFIX + "已公开奶牛猫", PREFIX + "管理员录入白猫"},
        )
        public_tasks = self._json("GET", "/api/v1/tasks")["items"]
        self.assertEqual([item["title"] for item in public_tasks if item["title"].startswith(PREFIX)], [PREFIX + "小区晚间补粮"])

        with sqlite3.connect(self.database) as connection:
            supers = connection.execute("SELECT username FROM users WHERE role = 'SUPER_ADMIN'").fetchall()
            self.assertEqual(supers, [("zack",)])
            self.assertEqual(
                {row[0] for row in connection.execute("SELECT DISTINCT action FROM audit_logs")},
                {"ROLE_CHANGE", "CREATE", "UPLOAD", "REVIEW", "VISIBILITY", "ARCHIVE", "CLAIM"},
            )
            active_zack_seed_sessions = connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = 'zack') AND revoked_at IS NULL"
            ).fetchone()[0]
            self.assertEqual(active_zack_seed_sessions, 1)  # registration session only; temporary seed session was removed

        with self.assertRaisesRegex(RuntimeError, "manifest already exists"):
            seed_full_flow(config, passwords)

        with sqlite3.connect(self.database) as connection:
            preview = cleanup(connection, self.storage, manifest, execute=False)
            self.assertEqual(preview["users"], 3)
            self.assertEqual(preview["cats"], 6)
            cleanup(connection, self.storage, manifest, execute=True)
            self.assertEqual(connection.execute("SELECT username, role FROM users").fetchall(), [("zack", "SUPER_ADMIN")])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM communities").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM cats").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
