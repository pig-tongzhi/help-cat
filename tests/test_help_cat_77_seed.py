import os
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.help_cat_77_seed import IDEMPOTENCY_KEY, PROFILE_KEY, SeedConfig, seed_77_profile


class FakeHttpClient:
    def __init__(self, role="ADMIN", duplicate=False):
        self.role = role
        self.duplicate = duplicate
        self.imports = []
        self.cat = None
        self.media = None

    def json(self, method, path, payload=None, token=None, expected=200):
        if (method, path) == ("POST", "/api/v1/auth/login"):
            return {"access_token": "test-token"}
        if (method, path) == ("GET", "/api/v1/auth/me"):
            return {"role": self.role}
        raise AssertionError("unexpected request: %s %s" % (method, path))

    def import_cat_draft(self, path, token, fields, idempotency_key, expected=201):
        self.imports.append((path, token, fields, idempotency_key, expected))
        if self.duplicate:
            raise RuntimeError("POST /api/v1/admin/cat-drafts/import returned 409 (profile_key_exists)")
        changed = self.cat is None
        if changed:
            self.media = {"id": "media-77"}
            self.cat = {
                "id": "cat-77", "profile_key": PROFILE_KEY, "photo_asset_id": "media-77",
                "review_status": "PENDING_REVIEW", "visibility_status": "HIDDEN",
            }
        return {"changed": changed, "cat": dict(self.cat), "media": dict(self.media)}


class HelpCat77SeedTests(unittest.TestCase):
    def setUp(self):
        self.config = SeedConfig(
            base_url="https://example.test",
            username="77-editor",
            password_env="HELP_CAT_77_PASSWORD",
            community_id="community-77",
            photo=Path("/approved/77.webp"),
        )

    @patch.dict(os.environ, {"HELP_CAT_77_PASSWORD": "only-in-environment"}, clear=False)
    def test_repeated_import_uses_one_atomic_draft_endpoint_and_fixed_idempotency_key(self):
        client = FakeHttpClient()

        first = seed_77_profile(self.config, client)
        second = seed_77_profile(self.config, client)

        self.assertEqual(first, {"cat_id": "cat-77", "media_id": "media-77", "changed": True})
        self.assertEqual(second, {"cat_id": "cat-77", "media_id": "media-77", "changed": False})
        self.assertEqual(len(client.imports), 2)
        for path, token, fields, idempotency_key, expected in client.imports:
            self.assertEqual(path, self.config.photo)
            self.assertEqual(token, "test-token")
            self.assertEqual(idempotency_key, IDEMPOTENCY_KEY)
            self.assertEqual(expected, 201)
            self.assertEqual(fields, {
                "community_id": "community-77",
                "profile_key": "story-77",
                "nickname": "77",
                "living_status": "已进入家庭",
                "health_status": "UNKNOWN",
                "location_note": "公开位置已保护；2025-06-02 相遇",
            })
        forbidden = {"gender", "vaccine", "sterilization", "health", "address", "latitude", "longitude"}
        self.assertFalse(forbidden & set(client.imports[0][2]))

    @patch.dict(os.environ, {"HELP_CAT_77_PASSWORD": "only-in-environment"}, clear=False)
    def test_importer_never_reviews_or_publishes_and_surfaces_duplicate_profile(self):
        client = FakeHttpClient(duplicate=True)
        with self.assertRaisesRegex(RuntimeError, "profile_key_exists"):
            seed_77_profile(self.config, client)
        self.assertEqual(len(client.imports), 1)

    @patch.dict(os.environ, {"HELP_CAT_77_PASSWORD": "only-in-environment"}, clear=False)
    def test_user_account_cannot_import(self):
        client = FakeHttpClient(role="USER")
        with self.assertRaisesRegex(RuntimeError, "ADMIN or SUPER_ADMIN"):
            seed_77_profile(self.config, client)
        self.assertEqual(client.imports, [])


if __name__ == "__main__":
    unittest.main()
