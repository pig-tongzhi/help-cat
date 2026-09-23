import asyncio
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from PIL import Image
from sqlalchemy import select

from server.helpcat.app import create_app
from server.helpcat.models import AuditLog, User


class AdminCatEditApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = self.build_app(Path(self.tmp.name))
        self.admin = self.login(self.app, "admin-openid")
        self.admin_token = self.admin["access_token"]
        self.user = self.login(self.app, "user-openid")
        self.user_token = self.user["access_token"]

    def tearDown(self):
        self.tmp.cleanup()

    def build_app(self, storage_root, **environment):
        with mock.patch.dict(os.environ, dict(environment), clear=False):
            return create_app("sqlite://", storage_root, fake_admin_openids={"admin-openid"})

    def request_on(self, app, method, path, token=None, payload=None, file_tuple=None):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        if file_tuple:
            boundary = "----HelpCatEditBoundary"
            filename, content, content_type = file_tuple
            body = (
                "--" + boundary + "\r\n"
                "Content-Disposition: form-data; name=\"file\"; filename=\"" + filename + "\"\r\n"
                "Content-Type: " + content_type + "\r\n\r\n"
            ).encode() + content + ("\r\n--" + boundary + "--\r\n").encode()
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        else:
            body = None
            if payload is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(payload).encode()
        return asyncio.run(self.asgi_request(app, method, path, headers, body))

    async def asgi_request(self, app, method, path, headers, body):
        parsed = urlsplit(path)
        sent = False
        messages = []

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body or b"", "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http", "http_version": "1.1", "method": method, "path": parsed.path,
            "raw_path": parsed.path.encode(), "query_string": parsed.query.encode(),
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
            "client": ("testclient", 50000), "server": ("testserver", 80), "scheme": "http",
        }
        await app(scope, receive, send)
        status = next(item["status"] for item in messages if item["type"] == "http.response.start")
        content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return status, (json.loads(content.decode()) if content else {})

    def login(self, app, openid):
        status, body = self.request_on(app, "POST", "/api/v1/auth/wechat-login", payload={"code": "fake:" + openid})
        self.assertEqual(status, 200)
        return body

    # ---- 脚手架 --------------------------------------------------------

    @staticmethod
    def jpeg_bytes(size=(8, 8)):
        image = Image.new("RGB", size, (231, 220, 205))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()

    def create_cat(self, **overrides):
        status, community = self.request_on(
            self.app, "POST", "/api/v1/communities", token=self.admin_token,
            payload={"name": "编辑测试小区", "street": "银湖街道"},
        )
        self.assertEqual(status, 201)
        payload = {
            "community_id": community["id"],
            "nickname": "小白",
            "location_note": "东门树下",
            "living_status": "常住",
            "health_status": "UNKNOWN",
        }
        payload.update(overrides)
        status, cat = self.request_on(self.app, "POST", "/api/v1/cats", token=self.admin_token, payload=payload)
        self.assertEqual(status, 201)
        return cat

    def upload_photo(self, token=None):
        status, asset = self.request_on(
            self.app, "POST", "/api/v1/media/images", token=token or self.admin_token,
            file_tuple=("cat.jpg", self.jpeg_bytes(), "image/jpeg"),
        )
        self.assertEqual(status, 201)
        return asset

    def patch_cat(self, cat_id, **payload):
        return self.request_on(
            self.app, "PATCH", "/api/v1/admin/cats/%s" % cat_id,
            token=self.admin_token, payload=payload,
        )

    def patch_cat_as(self, cat_id, token, **payload):
        return self.request_on(
            self.app, "PATCH", "/api/v1/admin/cats/%s" % cat_id, token=token, payload=payload,
        )

    def list_cats(self, token=None):
        status, body = self.request_on(self.app, "GET", "/api/v1/cats", token=token)
        self.assertEqual(status, 200)
        return body

    def find_cat(self, cat_id, token=None):
        for item in self.list_cats(token=token)["items"]:
            if item["id"] == cat_id:
                return item
        self.fail("cat %s missing from GET /api/v1/cats" % cat_id)

    def update_audit_rows(self, cat_id):
        with self.app.state.session_factory() as db:
            return db.scalars(select(AuditLog).where(
                AuditLog.action == "UPDATE", AuditLog.entity_type == "cat", AuditLog.entity_id == cat_id,
            )).all()

    # ---- 权限 ----------------------------------------------------------

    def test_anonymous_is_unauthorized_and_plain_user_is_forbidden(self):
        cat = self.create_cat()
        status, body = self.patch_cat_as(cat["id"], None, nickname="匿名改名")
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "unauthorized")
        status, body = self.patch_cat_as(cat["id"], self.user_token, nickname="用户改名")
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "forbidden")

    def test_admin_can_edit_a_cat(self):
        cat = self.create_cat()
        status, body = self.patch_cat(cat["id"], nickname="  大白  ")
        self.assertEqual(status, 200)
        self.assertEqual(body["nickname"], "大白")
        self.assertEqual(body["id"], cat["id"])

    def test_super_admin_can_edit_a_cat(self):
        cat = self.create_cat()
        status, body = self.request_on(
            self.app, "POST", "/api/v1/auth/register",
            payload={"username": "root-editor", "password": "strong-pass-1"},
        )
        self.assertEqual(status, 201)
        super_token = body["access_token"]
        with self.app.state.session_factory() as db:
            db.scalar(select(User).where(User.username == "root-editor")).role = "SUPER_ADMIN"
            db.commit()
        status, body = self.patch_cat_as(cat["id"], super_token, nickname="超级改名")
        self.assertEqual(status, 200)
        self.assertEqual(body["nickname"], "超级改名")

    def test_missing_cat_returns_cat_not_found(self):
        status, body = self.patch_cat("does-not-exist", nickname="无主猫")
        self.assertEqual((status, body["code"]), (404, "cat_not_found"))

    # ---- 照片关联 ------------------------------------------------------

    def test_admin_can_attach_an_uploaded_photo(self):
        cat = self.create_cat()
        self.assertIsNone(cat["photo_asset_id"])
        asset = self.upload_photo()
        status, body = self.patch_cat(cat["id"], photo_asset_id=asset["id"])
        self.assertEqual((status, body["photo_asset_id"]), (200, asset["id"]))
        # Follow-up admin read and public read both expose the attached photo.
        self.assertEqual(self.find_cat(cat["id"], token=self.admin_token)["photo_asset_id"], asset["id"])
        self.assertEqual(self.find_cat(cat["id"])["photo_asset_id"], asset["id"])

    def test_explicit_null_detaches_the_photo(self):
        cat = self.create_cat()
        asset = self.upload_photo()
        status, body = self.patch_cat(cat["id"], photo_asset_id=asset["id"])
        self.assertEqual((status, body["photo_asset_id"]), (200, asset["id"]))
        status, body = self.patch_cat(cat["id"], photo_asset_id=None)
        self.assertEqual(status, 200)
        self.assertIsNone(body["photo_asset_id"])
        self.assertIsNone(self.find_cat(cat["id"], token=self.admin_token)["photo_asset_id"])

    def test_unknown_photo_asset_returns_media_not_found(self):
        cat = self.create_cat()
        status, body = self.patch_cat(cat["id"], photo_asset_id="missing-asset-id")
        self.assertEqual((status, body["code"]), (404, "media_not_found"))
        self.assertIsNone(self.find_cat(cat["id"], token=self.admin_token)["photo_asset_id"])

    def test_nickname_only_edit_keeps_the_photo(self):
        cat = self.create_cat()
        asset = self.upload_photo()
        self.patch_cat(cat["id"], photo_asset_id=asset["id"])
        status, body = self.patch_cat(cat["id"], nickname="改名猫")
        self.assertEqual(status, 200)
        self.assertEqual(body["nickname"], "改名猫")
        self.assertEqual(body["photo_asset_id"], asset["id"])

    def test_photo_only_edit_keeps_the_nickname_and_other_fields(self):
        cat = self.create_cat()
        asset = self.upload_photo()
        status, body = self.patch_cat(cat["id"], photo_asset_id=asset["id"])
        self.assertEqual(status, 200)
        self.assertEqual(body["nickname"], cat["nickname"])
        self.assertEqual(body["location_note"], cat["location_note"])
        self.assertEqual(body["living_status"], cat["living_status"])
        self.assertEqual(body["health_status"], cat["health_status"])

    # ---- 校验与乐观锁 --------------------------------------------------

    def test_empty_body_is_rejected(self):
        cat = self.create_cat()
        status, _ = self.patch_cat(cat["id"])
        self.assertEqual(status, 422)

    def test_invalid_health_status_is_rejected(self):
        cat = self.create_cat()
        status, _ = self.patch_cat(cat["id"], health_status="SLEEPY")
        self.assertEqual(status, 422)

    def test_blank_nickname_is_rejected(self):
        cat = self.create_cat()
        status, _ = self.patch_cat(cat["id"], nickname="   ")
        self.assertEqual(status, 422)

    def test_stale_version_conflicts_and_correct_version_increments(self):
        cat = self.create_cat()
        self.assertEqual(cat["version"], 1)
        status, body = self.patch_cat(cat["id"], nickname="过期改名", version=cat["version"] + 1)
        self.assertEqual((status, body["code"]), (409, "version_conflict"))
        status, body = self.patch_cat(cat["id"], nickname="正常改名", version=cat["version"])
        self.assertEqual(status, 200)
        self.assertEqual(body["nickname"], "正常改名")
        self.assertEqual(body["version"], cat["version"] + 1)

    # ---- 审计 ----------------------------------------------------------

    def test_photo_attach_writes_exactly_one_update_audit_row(self):
        cat = self.create_cat()
        asset = self.upload_photo()
        self.patch_cat(cat["id"], nickname="审计猫", photo_asset_id=asset["id"])
        rows = self.update_audit_rows(cat["id"])
        self.assertEqual(len(rows), 1)
        before = json.loads(rows[0].before_json)
        after = json.loads(rows[0].after_json)
        self.assertEqual(before["nickname"], cat["nickname"])
        self.assertEqual(before["photo_asset_id"], cat["photo_asset_id"])
        self.assertEqual(after["nickname"], "审计猫")
        self.assertEqual(after["photo_asset_id"], asset["id"])
        self.assertEqual(after["version"], before["version"] + 1)


if __name__ == "__main__":
    unittest.main()
