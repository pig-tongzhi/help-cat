import os
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.help_cat_77_seed import SeedConfig, seed_77_profile


class FakeHttpClient:
    def __init__(self, role="ADMIN"):
        self.role = role
        self.public_cats = []
        self.admin_cats = []
        self.uploads = []
        self.creates = []
        self.reviews = []
        self.visibility_changes = []

    def json(self, method, path, payload=None, token=None, expected=200):
        if (method, path) == ("POST", "/api/v1/auth/login"):
            return {"access_token": "test-token"}
        if (method, path) == ("GET", "/api/v1/auth/me"):
            return {"role": self.role}
        if (method, path) == ("GET", "/api/v1/cats?q=2025-06-02%20%E7%9B%B8%E9%81%87"):
            return {"items": self.admin_cats if token else self.public_cats, "next_cursor": None}
        if method == "POST" and path == "/api/v1/cats":
            self.creates.append(payload)
            cat = {
                "id": "cat-77",
                "photo_asset_id": payload["photo_asset_id"],
                "review_status": "APPROVED",
                "visibility_status": "ACTIVE",
                "location_note": payload["location_note"],
            }
            self.public_cats.append(cat)
            self.admin_cats.append(cat)
            return cat
        if method == "POST" and path == "/api/v1/cats/cat-77/review":
            self.reviews.append(payload)
            self.admin_cats[0]["review_status"] = "APPROVED"
            return self.admin_cats[0]
        if method == "POST" and path == "/api/v1/cats/cat-77/visibility":
            self.visibility_changes.append(payload)
            self.admin_cats[0]["visibility_status"] = "ACTIVE"
            return self.admin_cats[0]
        raise AssertionError("unexpected request: %s %s" % (method, path))

    def upload_image(self, path, token, expected=201):
        self.uploads.append((path, token))
        return {"id": "media-77"}


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
    def test_repeated_import_creates_one_media_and_one_privacy_safe_cat(self):
        client = FakeHttpClient()

        first = seed_77_profile(self.config, client)
        second = seed_77_profile(self.config, client)

        self.assertEqual(first, {"cat_id": "cat-77", "media_id": "media-77", "changed": True})
        self.assertEqual(second, {"cat_id": "cat-77", "media_id": "media-77", "changed": False})
        self.assertEqual(client.uploads, [(Path("/approved/77.webp"), "test-token")])
        self.assertEqual(client.creates, [{
            "community_id": "community-77",
            "nickname": "77",
            "living_status": "已进入家庭",
            "health_status": "UNKNOWN",
            "location_note": "公开位置已保护；2025-06-02 相遇",
            "photo_asset_id": "media-77",
        }])
        forbidden = {"gender", "vaccine", "sterilization", "health", "address", "latitude", "longitude"}
        self.assertFalse(forbidden & set(client.creates[0]))

    @patch.dict(os.environ, {"HELP_CAT_77_PASSWORD": "only-in-environment"}, clear=False)
    def test_existing_pending_hidden_profile_is_approved_and_made_public_without_upload(self):
        client = FakeHttpClient()
        client.admin_cats.append({
            "id": "cat-77", "photo_asset_id": "media-77", "review_status": "PENDING_REVIEW",
            "visibility_status": "HIDDEN", "location_note": "公开位置已保护；2025-06-02 相遇",
        })

        result = seed_77_profile(self.config, client)

        self.assertEqual(result, {"cat_id": "cat-77", "media_id": "media-77", "changed": True})
        self.assertEqual(client.uploads, [])
        self.assertEqual(client.creates, [])
        self.assertEqual(client.reviews, [{"approved": True}])
        self.assertEqual(client.visibility_changes, [{"visible": True}])

    @patch.dict(os.environ, {"HELP_CAT_77_PASSWORD": "only-in-environment"}, clear=False)
    def test_user_account_cannot_import_or_review(self):
        with self.assertRaisesRegex(RuntimeError, "ADMIN or SUPER_ADMIN"):
            seed_77_profile(self.config, FakeHttpClient(role="USER"))


if __name__ == "__main__":
    unittest.main()
