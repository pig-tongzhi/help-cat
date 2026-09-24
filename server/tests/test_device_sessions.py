"""长期设备会话：签发、设备列表、撤销。

不动表结构：会话表只有 token / expires_at / revoked_at，设备与登录时间落在
SESSION_ISSUE 审计里，用令牌前 8 位对齐。这里把三条口径钉死：
  1. 勾了「记住这台设备」→ 90 天，否则常规 30 天；
  2. 列表只给令牌前 8 位，且只列自己名下的会话，本机要标出来；
  3. 撤销是服务端行为，被撤销的令牌立刻失效；本机不能从列表里撤（要走 logout）。
"""
import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from server.helpcat.app import create_app
from server.helpcat.models import AuditLog, Session as AuthSession


def days_until(value):
    moment = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return (moment - datetime.now(timezone.utc)).days


class DeviceSessionApiTests(unittest.TestCase):
    def setUp(self):
        self.last_cookie = ""
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app("sqlite://", Path(self.tmp.name), fake_admin_openids={"admin-openid"})
        self.admin = self.register("zack", "99bu88ZZK..")

    def tearDown(self):
        self.tmp.cleanup()

    async def asgi_request(self, app, method, path, headers, body, client=("testclient", 50000)):
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
        start = next(item for item in messages if item["type"] == "http.response.start")
        content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        cookies = [value.decode() for key, value in start.get("headers", []) if key.lower() == b"set-cookie"]
        self.last_cookie = cookies[0] if cookies else ""
        return start["status"], (json.loads(content.decode()) if content else {})

    def request_on(self, method, path, token=None, payload=None, user_agent=None):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        if user_agent:
            headers["User-Agent"] = user_agent
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        return asyncio.run(self.asgi_request(self.app, method, path, headers, body))

    def register(self, username, password):
        with mock.patch.dict(os.environ, {"HELPCAT_ALLOW_FAKE_WECHAT": "1"}, clear=False):
            status, body = self.request_on("POST", "/api/v1/auth/register", payload={"username": username, "password": password})
        self.assertEqual(status, 201, body)
        return body

    def login(self, password="99bu88ZZK..", remember=False, user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)"):
        status, body = self.request_on("POST", "/api/v1/auth/login",
                                       payload={"username": "zack", "password": password, "remember": remember},
                                       user_agent=user_agent)
        self.assertEqual(status, 200, body)
        return body

    def sessions(self, token):
        status, body = self.request_on("GET", "/api/v1/auth/sessions", token=token)
        self.assertEqual(status, 200, body)
        return body["items"]

    # ---- 有效期 ---------------------------------------------------------

    def test_sessions_live_thirty_days_either_way(self):
        """勾不勾"记住设备"都是 30 天：差别在存在哪（localStorage/Cookie vs sessionStorage），
        不在活多久。"""
        plain = self.login(remember=False)
        long_lived = self.login(remember=True)
        with self.app.state.session_factory() as db:
            rows = {item.token: days_until(item.expires_at) for item in db.query(AuthSession).all()}
        self.assertAlmostEqual(30, rows[plain["access_token"]], delta=1)
        self.assertAlmostEqual(30, rows[long_lived["access_token"]], delta=1)

    def test_session_cookie_alone_authenticates(self):
        """微信内置浏览器会清 JS 存储，所以登录必须同时下发 HttpOnly Cookie，
        而且**只带 Cookie、不带 Authorization** 也要能认出用户。"""
        status, body = self.request_on(
            "POST", "/api/v1/auth/login",
            payload={"username": "zack", "password": "99bu88ZZK..", "remember": True},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)",
        )
        self.assertEqual(200, status, body)
        cookie = self.last_cookie
        self.assertTrue(cookie, "登录响应里必须有 Set-Cookie")
        self.assertIn("httponly", cookie.lower())
        self.assertIn("samesite=lax", cookie.lower())
        token = cookie.split("helpcat_session=", 1)[1].split(";", 1)[0]
        # 只带 Cookie（用 Header 模拟浏览器自动携带）
        status, me = asyncio.run(self.asgi_request(
            self.app, "GET", "/api/v1/auth/me",
            {"cookie": "helpcat_session=" + token}, None,
        ))
        self.assertEqual(200, status, me)
        self.assertEqual("zack", me["username"])

    # ---- 设备列表 -------------------------------------------------------

    def test_list_marks_the_current_device_and_labels_the_others(self):
        phone = self.login(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)")
        desktop = self.login(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        items = self.sessions(phone["access_token"])
        # 注册本身也会建一个会话，所以不能断言总数，只断言两台设备都在
        by_device = {item["device"]: item for item in items}
        self.assertIn("iPhone / iPad", by_device)
        self.assertIn("Mac", by_device)
        self.assertTrue(by_device["iPhone / iPad"]["current"], "本机要标出来")
        self.assertFalse(by_device["Mac"]["current"])
        # 只给前 8 位，完整令牌绝不能出现在响应里
        self.assertTrue(all(len(item["id"]) == 8 for item in items))
        for item in items:
            self.assertNotIn(phone["access_token"], json.dumps(item))
            self.assertNotIn(desktop["access_token"], json.dumps(item))

    def test_issue_is_audited_with_device_and_ip(self):
        self.login(remember=True, user_agent="Mozilla/5.0 (Linux; Android 14)")
        with self.app.state.session_factory() as db:
            row = db.query(AuditLog).filter(AuditLog.action == "SESSION_ISSUE").one()
            payload = json.loads(row.after_json)
        self.assertEqual("Android 手机", payload["device"])
        self.assertTrue(payload["remember"])
        self.assertEqual(30, payload["days"])

    # ---- 撤销 -----------------------------------------------------------

    def test_revoke_kills_the_other_device_and_keeps_the_caller(self):
        phone = self.login(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)")
        desktop = self.login(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        before = {item["id"] for item in self.sessions(phone["access_token"])}
        target = next(item for item in self.sessions(phone["access_token"]) if item["device"] == "Mac")

        status, body = self.request_on("POST", "/api/v1/auth/sessions/revoke", token=phone["access_token"], payload={"id": target["id"]})
        self.assertEqual(200, status, body)

        status, _ = self.request_on("GET", "/api/v1/auth/me", token=desktop["access_token"])
        self.assertEqual(401, status, "被踢的设备必须立刻失效")
        status, _ = self.request_on("GET", "/api/v1/auth/me", token=phone["access_token"])
        self.assertEqual(200, status, "自己不能被误伤")
        after = {item["id"] for item in self.sessions(phone["access_token"])}
        self.assertEqual(before - {target["id"]}, after, "被撤销的那条要从列表里消失，其余不动")

    def test_cannot_revoke_the_current_session(self):
        phone = self.login()
        current = next(item for item in self.sessions(phone["access_token"]) if item["current"])
        status, body = self.request_on("POST", "/api/v1/auth/sessions/revoke", token=phone["access_token"], payload={"id": current["id"]})
        self.assertEqual(400, status, body)
        self.assertEqual("cannot_revoke_current_session", body.get("code") or body.get("detail", {}).get("code"))

    def test_cannot_revoke_someone_elses_session(self):
        other = self.register("other", "another-pass-123")
        mine = self.login()
        target = next(item for item in self.sessions(mine["access_token"]) if item["current"])
        status, body = self.request_on("POST", "/api/v1/auth/sessions/revoke", token=other["access_token"], payload={"id": target["id"]})
        self.assertEqual(404, status, body)
        status, _ = self.request_on("GET", "/api/v1/auth/me", token=mine["access_token"])
        self.assertEqual(200, status)


if __name__ == "__main__":
    unittest.main()
