import json
import asyncio
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from sqlalchemy import select

from server.helpcat.app import create_app
from server.helpcat.models import AuditLog, User


class CommercialApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app("sqlite://", Path(self.tmp.name), fake_admin_openids={"admin-openid"})
        self.user_token = self.login("user-openid")
        self.admin_token = self.login("admin-openid")
        status, body = self.request("POST", "/api/v1/auth/register", payload={"username": "zack", "password": "super-pass-1"})
        self.assertEqual(status, 201)
        self.super_token = body["access_token"]
        with self.app.state.session_factory() as db:
            zack = db.scalar(select(User).where(User.username == "zack"))
            zack.role = "SUPER_ADMIN"
            self.super_id = zack.id
            self.user_id = db.scalar(select(User).where(User.openid == "user-openid")).id
            db.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, method, path, token=None, payload=None, file_tuple=None):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        if file_tuple:
            boundary = "----HelpCatBoundary"
            filename, content, content_type = file_tuple
            body = ("--" + boundary + "\r\n" + "Content-Disposition: form-data; name=\"file\"; filename=\"" + filename + "\"\r\n" + "Content-Type: " + content_type + "\r\n\r\n").encode() + content + ("\r\n--" + boundary + "--\r\n").encode()
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        else:
            body = json.dumps(payload).encode() if payload is not None else None
            if body is not None:
                headers["Content-Type"] = "application/json"
        return asyncio.run(self.asgi_request(method, path, headers, body))

    async def asgi_request(self, method, path, headers, body):
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
            "type": "http", "http_version": "1.1", "method": method, "path": path,
            "raw_path": path.encode(), "query_string": b"", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("testclient", 50000), "server": ("testserver", 80), "scheme": "http",
        }
        await self.app(scope, receive, send)
        status = next(item["status"] for item in messages if item["type"] == "http.response.start")
        content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return status, json.loads(content.decode())

    def login(self, openid):
        status, body = self.request("POST", "/api/v1/auth/wechat-login", payload={"code": "fake:" + openid})
        self.assertEqual(status, 200)
        return body["access_token"]

    def test_health_and_wechat_login_return_production_api_shape(self):
        status, body = self.request("GET", "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_password_registration_and_login_create_user_session(self):
        status, body = self.request("POST", "/api/v1/auth/register", payload={"username": "猫咪志愿者", "password": "strong-pass-1"})
        self.assertEqual(status, 201)
        self.assertEqual(body["user"]["role"], "USER")
        status, login = self.request("POST", "/api/v1/auth/login", payload={"username": "猫咪志愿者", "password": "strong-pass-1"})
        self.assertEqual(status, 200)
        self.assertTrue(login["access_token"])
        status, _ = self.request("POST", "/api/v1/auth/login", payload={"username": "猫咪志愿者", "password": "wrong-pass"})
        self.assertEqual(status, 401)
        status, _ = self.request("POST", "/api/v1/auth/logout", login["access_token"])
        self.assertEqual(status, 200)
        status, _ = self.request("POST", "/api/v1/communities", login["access_token"], {"name": "退出后禁止操作", "street": "银湖街道"})
        self.assertEqual(status, 401)

    def test_authenticated_user_can_restore_session(self):
        status, body = self.request("GET", "/api/v1/auth/me", self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(body["role"], "ADMIN")
        self.assertTrue(body["id"])

    def test_super_admin_can_list_users_without_sensitive_fields(self):
        status, body = self.request("GET", "/api/v1/admin/users", self.super_token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(body["items"]), 3)
        zack = next(item for item in body["items"] if item["username"] == "zack")
        self.assertEqual(zack["role"], "SUPER_ADMIN")
        for sensitive in ("password_hash", "openid", "access_token", "token"):
            self.assertNotIn(sensitive, zack)

    def test_super_admin_can_promote_and_demote_user_with_audit(self):
        status, body = self.request("POST", "/api/v1/admin/users/%s/role" % self.user_id, self.super_token, {"role": "ADMIN"})
        self.assertEqual((status, body["role"]), (200, "ADMIN"))
        status, body = self.request("POST", "/api/v1/admin/users/%s/role" % self.user_id, self.super_token, {"role": "ADMIN"})
        self.assertEqual((status, body["role"]), (200, "ADMIN"))
        status, body = self.request("POST", "/api/v1/admin/users/%s/role" % self.user_id, self.super_token, {"role": "USER"})
        self.assertEqual((status, body["role"]), (200, "USER"))
        with self.app.state.session_factory() as db:
            logs = db.scalars(select(AuditLog).where(AuditLog.action == "ROLE_CHANGE", AuditLog.entity_id == self.user_id)).all()
            self.assertEqual(len(logs), 2)

    def test_only_super_admin_can_manage_roles_and_super_admin_is_immutable(self):
        status, body = self.request("GET", "/api/v1/admin/users", self.admin_token)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "super_admin_required")
        status, _ = self.request("POST", "/api/v1/admin/users/%s/role" % self.user_id, self.admin_token, {"role": "ADMIN"})
        self.assertEqual(status, 403)
        status, body = self.request("POST", "/api/v1/admin/users/%s/role" % self.super_id, self.super_token, {"role": "ADMIN"})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "super_admin_immutable")
        status, _ = self.request("POST", "/api/v1/admin/users/missing/role", self.super_token, {"role": "ADMIN"})
        self.assertEqual(status, 404)
        status, _ = self.request("POST", "/api/v1/admin/users/%s/role" % self.user_id, self.super_token, {"role": "SUPER_ADMIN"})
        self.assertEqual(status, 422)

    def test_super_admin_keeps_content_governance_permissions(self):
        status, community = self.request("POST", "/api/v1/communities", self.super_token, {"name": "超级管理员小区", "street": "银湖街道"})
        self.assertEqual(status, 201)
        self.assertEqual(community["status"], "ACTIVE")

    def test_admin_cat_creation_is_approved_immediately(self):
        _, community = self.request("POST", "/api/v1/communities", self.admin_token, {"name": "管理员审核小区", "street": "银湖街道"})
        status, cat = self.request("POST", "/api/v1/cats", self.admin_token, {"community_id": community["id"], "nickname": "管理员猫", "location_note": "东门"})
        self.assertEqual(status, 201)
        self.assertEqual(cat["review_status"], "APPROVED")
        self.assertEqual(len(self.request("GET", "/api/v1/cats")[1]["items"]), 1)

    def test_user_can_suggest_community_but_admin_only_can_approve(self):
        status, body = self.request("POST", "/api/v1/communities", self.user_token, {"name": "聚源福小区", "street": "银湖街道"})
        self.assertEqual(status, 201)
        community_id = body["id"]
        self.assertEqual(body["status"], "PENDING_REVIEW")
        status, _ = self.request("POST", "/api/v1/communities/%s/review" % community_id, self.user_token, {"approved": True})
        self.assertEqual(status, 403)
        status, body = self.request("POST", "/api/v1/communities/%s/review" % community_id, self.admin_token, {"approved": True})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ACTIVE")

    def test_user_cat_is_pending_and_fourth_cat_is_rejected(self):
        _, community = self.request("POST", "/api/v1/communities", self.admin_token, {"name": "银湖商业小区", "street": "银湖街道"})
        for index in range(3):
            status, body = self.request("POST", "/api/v1/cats", self.user_token, {"community_id": community["id"], "nickname": "猫%d" % index, "location_note": "东门"})
            self.assertEqual(status, 201)
            self.assertEqual(body["review_status"], "PENDING_REVIEW")
        status, body = self.request("POST", "/api/v1/cats", self.user_token, {"community_id": community["id"], "nickname": "猫3", "location_note": "东门"})
        self.assertEqual(status, 429)
        self.assertEqual(body["code"], "daily_cat_limit_reached")

    def test_admin_can_approve_hide_and_archive_cat(self):
        _, community = self.request("POST", "/api/v1/communities", self.admin_token, {"name": "管理小区", "street": "银湖街道"})
        _, cat = self.request("POST", "/api/v1/cats", self.user_token, {"community_id": community["id"], "nickname": "小拉", "location_note": "3幢附近"})
        status, _ = self.request("POST", "/api/v1/cats/%s/review" % cat["id"], self.admin_token, {"approved": True})
        self.assertEqual(status, 200)
        status, body = self.request("POST", "/api/v1/cats/%s/visibility" % cat["id"], self.admin_token, {"visible": False})
        self.assertEqual(status, 200)
        self.assertEqual(body["visibility_status"], "HIDDEN")
        status, body = self.request("POST", "/api/v1/cats/%s/archive" % cat["id"], self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(body["visibility_status"], "ARCHIVED")
        self.assertEqual(self.request("GET", "/api/v1/cats")[1]["items"], [])
        self.assertEqual(len(self.request("GET", "/api/v1/cats", self.admin_token)[1]["items"]), 1)

    def test_image_upload_rejects_non_image_and_accepts_small_image(self):
        status, _ = self.request("POST", "/api/v1/media/images", self.user_token, file_tuple=("note.txt", b"hello", "text/plain"))
        self.assertEqual(status, 415)
        status, _ = self.request("POST", "/api/v1/media/images", self.user_token, file_tuple=("fake.jpg", b"not-an-image", "image/jpeg"))
        self.assertEqual(status, 415)
        status, body = self.request("POST", "/api/v1/media/images", self.user_token, file_tuple=("cat.jpg", b"\xff\xd8\xff\xe0fake-jpeg", "image/jpeg"))
        self.assertEqual(status, 201)
        self.assertTrue(body["object_key"])


if __name__ == "__main__":
    unittest.main()
