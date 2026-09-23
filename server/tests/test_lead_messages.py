import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from sqlalchemy import select

from server.helpcat.app import create_app
from server.helpcat.models import AuditLog, LeadMessage

CONTACT_ENV = {
    "HELPCAT_ADMIN_WECHAT": "mantaooo1",
    "HELPCAT_ADMIN_WECHAT_NOTE": "帮帮小猫",
    "HELPCAT_ADMIN_QR_IMAGE": "/assets/admin-wechat-qr.png",
    "HELPCAT_ADMIN_CONTACT_NOTE": "个人业余发起 · 有空时回复，不承诺随时响应",
}


class LeadMessageApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = self.build_app(Path(self.tmp.name))
        self.admin_token = self.login(self.app, "admin-openid")
        self.user_token = self.login(self.app, "user-openid")

    def tearDown(self):
        self.tmp.cleanup()

    def build_app(self, storage_root, **environment):
        with mock.patch.dict(os.environ, dict(CONTACT_ENV, **environment), clear=False):
            return create_app("sqlite://", storage_root, fake_admin_openids={"admin-openid"})

    def request_on(self, app, method, path, token=None, payload=None, client=("testclient", 50000)):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        return asyncio.run(self.asgi_request(app, method, path, headers, body, client))

    async def asgi_request(self, app, method, path, headers, body, client):
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
            "client": client, "server": ("testserver", 80), "scheme": "http",
        }
        await app(scope, receive, send)
        status = next(item["status"] for item in messages if item["type"] == "http.response.start")
        content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return status, (json.loads(content.decode()) if content else {})

    def login(self, app, openid):
        status, body = self.request_on(app, "POST", "/api/v1/auth/wechat-login", payload={"code": "fake:" + openid})
        self.assertEqual(status, 200)
        return body["access_token"]

    def submit(self, app=None, client=("testclient", 50000), **overrides):
        payload = {"name": "小张", "contact_type": "WECHAT", "contact": "zhang-wx", "message": "想参与投喂"}
        payload.update(overrides)
        return self.request_on(app or self.app, "POST", "/api/v1/public/messages", payload=payload, client=client)

    def test_welcome_page_reads_operator_channels_without_leaking_leads(self):
        status, body = self.request_on(self.app, "GET", "/api/v1/public/contact")
        self.assertEqual(status, 200)
        self.assertEqual(body["wechat"], "mantaooo1")
        self.assertEqual(body["wechat_note"], "帮帮小猫")
        self.assertEqual(body["qr_image"], "/assets/admin-wechat-qr.png")
        self.assertEqual(body["note"], "个人业余发起 · 有空时回复，不承诺随时响应")
        self.assertNotIn("messages", body)
        self.assertNotIn("items", body)

    def test_visitor_without_an_account_can_leave_a_contact(self):
        status, body = self.submit()
        self.assertEqual(status, 201)
        self.assertEqual(body["name"], "小张")
        self.assertEqual(body["contact"], "zhang-wx")
        self.assertEqual(body["contact_type"], "WECHAT")
        self.assertEqual(body["message"], "想参与投喂")
        self.assertEqual(body["status"], "NEW")
        self.assertIsNone(body["handled_at"])
        self.assertTrue(body["created_at"])

    def test_a_visitor_without_a_name_is_recorded_as_the_default_one(self):
        """欢迎页的称呼是可选的；留空时统一落成「喜猫人」，不能是空字符串。"""
        status, body = self.submit(name="", contact="no-name-wx")
        self.assertEqual(201, status)
        self.assertEqual("喜猫人", body["name"])

        status, body = self.submit(name="   ", contact="blank-name-wx")
        self.assertEqual(201, status)
        self.assertEqual("喜猫人", body["name"], "只有空白也算没填")

        status, body = self.submit(name="阿咪", contact="with-name-wx")
        self.assertEqual(201, status)
        self.assertEqual("阿咪", body["name"], "填了就用填的")

    def test_contact_is_trimmed_and_a_blank_contact_is_rejected(self):
        status, body = self.submit(name="  小张  ", contact="  zhang-wx  ")
        self.assertEqual(status, 201)
        self.assertEqual(body["name"], "小张")
        self.assertEqual(body["contact"], "zhang-wx")

        status, _ = self.submit(contact="   ")
        self.assertEqual(status, 422)
        with self.app.state.session_factory() as db:
            self.assertEqual(len(db.scalars(select(LeadMessage)).all()), 1)

    def test_the_same_contact_submitted_twice_is_stored_once(self):
        first = self.submit(contact="repeat-wx")[1]
        second = self.submit(contact="repeat-wx", message="补充一句")[1]
        self.assertEqual(first["id"], second["id"])
        with self.app.state.session_factory() as db:
            rows = db.scalars(select(LeadMessage).where(LeadMessage.contact == "repeat-wx")).all()
        self.assertEqual(len(rows), 1)

    def test_one_client_cannot_flood_the_message_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = self.build_app(Path(tmp), HELPCAT_LEAD_RATE_LIMIT_PER_HOUR="2")
            self.assertEqual(self.submit(app=app, contact="rate-0")[0], 201)
            self.assertEqual(self.submit(app=app, contact="rate-1")[0], 201)
            status, body = self.submit(app=app, contact="rate-2")
            self.assertEqual(status, 429)
            self.assertEqual(body["code"], "too_many_messages")
            # A different visitor is unaffected.
            self.assertEqual(self.submit(app=app, contact="rate-3", client=("other-client", 50001))[0], 201)

    def test_admin_lists_and_triages_leads_with_a_new_count(self):
        self.submit(contact="lead-a")
        self.submit(contact="lead-b")
        status, body = self.request_on(self.app, "GET", "/api/v1/admin/messages", token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(body["new_count"], 2)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual({item["contact"] for item in body["items"]}, {"lead-a", "lead-b"})

        target = body["items"][0]["id"]
        status, updated = self.request_on(
            self.app, "POST", "/api/v1/admin/messages/%s/status" % target,
            token=self.admin_token, payload={"status": "CONTACTED", "note": "已加微信"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["status"], "CONTACTED")
        self.assertEqual(updated["admin_note"], "已加微信")
        self.assertIsNotNone(updated["handled_at"])

        status, body = self.request_on(self.app, "GET", "/api/v1/admin/messages?status=NEW", token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["new_count"], 1)

    def test_triage_is_written_to_the_audit_log(self):
        message_id = self.submit(contact="audit-lead")[1]["id"]
        self.request_on(
            self.app, "POST", "/api/v1/admin/messages/%s/status" % message_id,
            token=self.admin_token, payload={"status": "CLOSED", "note": "已联系"},
        )
        with self.app.state.session_factory() as db:
            logs = db.scalars(select(AuditLog).where(
                AuditLog.entity_type == "lead_message", AuditLog.entity_id == message_id,
            )).all()
        self.assertEqual([log.action for log in logs], ["LEAD_MESSAGE_STATUS"])
        self.assertEqual(json.loads(logs[0].before_json)["status"], "NEW")
        self.assertEqual(json.loads(logs[0].after_json)["status"], "CLOSED")
        self.assertEqual(json.loads(logs[0].after_json)["admin_note"], "已联系")

    def test_regular_user_cannot_read_or_triage_leads(self):
        message_id = self.submit(contact="guarded-lead")[1]["id"]
        status, body = self.request_on(self.app, "GET", "/api/v1/admin/messages", token=self.user_token)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "forbidden")
        status, _ = self.request_on(
            self.app, "POST", "/api/v1/admin/messages/%s/status" % message_id,
            token=self.user_token, payload={"status": "CLOSED"},
        )
        self.assertEqual(status, 403)
        status, _ = self.request_on(self.app, "GET", "/api/v1/admin/messages")
        self.assertEqual(status, 401)

    def test_unknown_lead_cannot_be_triaged(self):
        status, body = self.request_on(
            self.app, "POST", "/api/v1/admin/messages/does-not-exist/status",
            token=self.admin_token, payload={"status": "CLOSED"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "lead_message_not_found")

    def test_invalid_triage_status_is_rejected(self):
        message_id = self.submit(contact="bad-status")[1]["id"]
        status, _ = self.request_on(
            self.app, "POST", "/api/v1/admin/messages/%s/status" % message_id,
            token=self.admin_token, payload={"status": "DONE"},
        )
        self.assertEqual(status, 422)


if __name__ == "__main__":
    unittest.main()
