"""安全加固的行为断言：假登录、API 文档、登录限速。

这三项都是"默认就该是关的"那一类 —— 一旦默认写反，线上就多一个后门或一个爆破点。
所以这里既测关（默认），也测开（显式打开时仍然可用），避免以后改配置时把功能弄死。
"""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from server.helpcat.app import create_app
from server.helpcat.auth import hash_password
from server.helpcat.models import User


class SecurityTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def build_app(self, **environment):
        """按给定的环境变量建 app：默认不带任何 HELPCAT_* 开关。"""
        cleaned = {key: value for key, value in os.environ.items() if not key.startswith("HELPCAT_ALLOW_FAKE_WECHAT")}
        cleaned = {key: value for key, value in cleaned.items() if not key.startswith("HELPCAT_EXPOSE_API_DOCS")}
        cleaned.update(environment)
        with mock.patch.dict(os.environ, cleaned, clear=True):
            return create_app("sqlite://", storage_root=self.root)

    def add_user(self, app, username="ops", password="ops-password", role="ADMIN"):
        with app.state.session_factory() as db:
            db.add(User(id="u-" + username, openid="local:" + username, username=username,
                        password_hash=hash_password(password), role=role, nickname=username))
            db.commit()

    def request(self, app, method, path, payload=None, client_ip="203.0.113.9"):
        status, _headers, content = asyncio.run(self.asgi_request(app, method, path, payload, client_ip))
        return status, (json.loads(content.decode()) if content else {})

    async def asgi_request(self, app, method, path, payload, client_ip):
        headers, body = {}, None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
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

        await app({
            "type": "http", "http_version": "1.1", "method": method, "path": parsed.path,
            "raw_path": parsed.path.encode(), "query_string": parsed.query.encode(),
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
            "client": (client_ip, 50000), "server": ("testserver", 80), "scheme": "http",
        }, receive, send)
        start = next(item for item in messages if item["type"] == "http.response.start")
        content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return start["status"], {}, content


class FakeWechatLoginTests(SecurityTestCase):
    def test_fake_login_is_closed_by_default(self):
        """默认不许用 fake: 换会话 —— 线上没配微信凭据时它就是万能登录后门。"""
        app = self.build_app()
        status, body = self.request(app, "POST", "/api/v1/auth/wechat-login", {"code": "fake:anyone"})
        self.assertEqual(503, status, body)
        self.assertEqual("wechat_not_configured", body["code"])

    def test_fake_login_still_works_when_explicitly_enabled(self):
        app = self.build_app(HELPCAT_ALLOW_FAKE_WECHAT="1")
        status, body = self.request(app, "POST", "/api/v1/auth/wechat-login", {"code": "fake:someone"})
        self.assertEqual(200, status, body)
        self.assertIn("access_token", body)


class ApiDocsTests(SecurityTestCase):
    def test_api_docs_are_hidden_by_default(self):
        app = self.build_app()
        for path in ("/docs", "/redoc", "/openapi.json"):
            status, _body = self.request(app, "GET", path)
            self.assertEqual(404, status, "%s 不该公开" % path)

    def test_api_docs_can_be_exposed_for_local_development(self):
        app = self.build_app(HELPCAT_EXPOSE_API_DOCS="1")
        self.assertEqual(200, self.request(app, "GET", "/openapi.json")[0])


class LoginThrottleTests(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.build_app()
        self.add_user(self.app)
        self.app.state.settings.login_rate_limit_per_account = 3
        self.app.state.settings.login_rate_limit_per_ip = 5

    def login(self, password="wrong-password", username="ops", client_ip="203.0.113.9"):
        return self.request(self.app, "POST", "/api/v1/auth/login",
                            {"username": username, "password": password}, client_ip=client_ip)

    def test_repeated_failures_for_one_account_are_throttled(self):
        for attempt in range(3):
            status, body = self.login()
            self.assertEqual(401, status, "第 %d 次应该是密码错误" % (attempt + 1))

        status, body = self.login()
        self.assertEqual(429, status, body)
        self.assertEqual("too_many_login_attempts", body["code"])
        self.assertIn("分钟", body["message"])

        # 限速期间即使密码是对的也不放行（否则爆破者只需要等到猜中）
        status, body = self.login(password="ops-password")
        self.assertEqual(429, status, body)

    def test_a_successful_login_clears_the_failures(self):
        self.assertEqual(401, self.login()[0])
        self.assertEqual(401, self.login()[0])
        status, body = self.login(password="ops-password")
        self.assertEqual(200, status, body)
        # 成功之后失败计数清零：又能正常试错，不会把自己锁死
        self.assertEqual(401, self.login()[0])
        self.assertEqual(401, self.login()[0])
        self.assertEqual(200, self.login(password="ops-password")[0])

    def test_scanning_many_accounts_from_one_ip_is_throttled(self):
        """换账号名继续猜也要被挡住 —— 只看账号的限速拦不住这种扫号。"""
        for index in range(5):
            status, _body = self.login(username="nobody-%d" % index, client_ip="198.51.100.7")
            self.assertEqual(401, status)
        status, body = self.login(username="nobody-again", client_ip="198.51.100.7")
        self.assertEqual(429, status, body)

        # 另一个 IP 不受影响
        self.assertEqual(401, self.login(username="nobody-other", client_ip="198.51.100.8")[0])


if __name__ == "__main__":
    unittest.main()
