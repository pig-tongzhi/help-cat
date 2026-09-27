"""长期设备会话：签发、设备列表、撤销。

不动表结构：会话表只有 token / expires_at / revoked_at，设备与登录时间落在
SESSION_ISSUE 审计里，用令牌前 8 位对齐。这里把三条口径钉死：
  1. 勾了「记住这台设备」→ 30 天，否则常规 30 天；
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


class DeviceLinkApiTests(DeviceSessionApiTests):
    """免登录链接：把一条长期会话的令牌放进 URL 的 ?k=，不依赖浏览器存储。

    为什么需要它：iOS 微信的 WKWebView 退出微信后会把 Cookie 和 localStorage 一起丢掉
    （线上实测同一台 iPhone 每次重开微信 /auth/me 都是 401），链接里的令牌不受影响。
    这里钉死四条：只有管理员能生成、令牌能直接换回会话、列表里标成免登录链接、
    踢下线之后立刻失效。
    """

    def admin_login(self, openid="admin-openid"):
        status, body = self.request_on("POST", "/api/v1/auth/wechat-login", payload={"code": "fake:" + openid})
        self.assertEqual(200, status, body)
        return body

    def create_link(self, token, label="我的 iPhone", days=None):
        payload = {"label": label}
        if days is not None:
            payload["days"] = days
        return self.request_on("POST", "/api/v1/auth/device-links", token=token, payload=payload)

    def test_admin_link_logs_in_without_password(self):
        admin = self.admin_login()
        status, body = self.create_link(admin["access_token"], label="我的 iPhone")
        self.assertEqual(201, status, body)
        self.assertEqual(180, body["days"], "默认 180 天，够用又留了撤销的余地")
        self.assertTrue(body["token"], "生成时必须回显完整令牌一次，前端才好拼进链接")

        # 链接里的令牌就是会话令牌：不用密码、不用 Cookie 也能认出人
        status, me = self.request_on("GET", "/api/v1/auth/me", token=body["token"])
        self.assertEqual(200, status, me)
        self.assertEqual(admin["user"]["id"], me["id"], "链接换回来的必须是生成它的那个账号")
        self.assertEqual("ADMIN", me["role"])

        # 「登录的设备」里要能认出哪条是免登录链接，否则撤销时无从下手
        item = next(one for one in self.sessions(body["token"]) if one["id"] == body["id"])
        self.assertTrue(item["link"])
        self.assertEqual("我的 iPhone", item["device"])

    def test_only_admins_can_create_links(self):
        """免登录链接等于免密码进门，所以只有管理员能生成。
        （令牌签给生成者自己，也就没有"替别人签一条"的口子。）"""
        ordinary = self.register("volunteer", "volunteer-pass-123")
        status, body = self.create_link(ordinary["access_token"])
        self.assertEqual(403, status, body)
        self.assertEqual("forbidden", body.get("code") or body.get("detail", {}).get("code"))

    def test_link_days_are_bounded(self):
        admin = self.admin_login()
        self.assertEqual(422, self.create_link(admin["access_token"], days=0)[0])
        self.assertEqual(422, self.create_link(admin["access_token"], days=3650)[0])

    def test_revoking_a_link_kills_it(self):
        admin = self.admin_login()
        _, link = self.create_link(admin["access_token"], label="备用入口")
        status, body = self.request_on("POST", "/api/v1/auth/sessions/revoke",
                                       token=admin["access_token"], payload={"id": link["id"]})
        self.assertEqual(200, status, body)
        status, _ = self.request_on("GET", "/api/v1/auth/me", token=link["token"])
        self.assertEqual(401, status, "踢下线后链接必须立刻失效")


if __name__ == "__main__":
    unittest.main()
