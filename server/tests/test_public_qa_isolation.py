"""公开读接口必须把 QA 数据挡在外面。

`scripts/help_cat_qa_seed.py` 造的验收数据用 `is_qa=1` 标记，只为内部验收存在。
较新的公开路由（`/cats/{id}/events`、`/public/profiles/{key}`、投喂系列）都带了
`is_qa` 过滤，但三条**早期**的公开列表漏了：`/communities`、`/cats`、`/tasks`。
只要 QA 数据挂在 ACTIVE 小区上，访客就会看到它 —— 生产库里当时正好没有这种组合，
所以一直没暴露。

这里用行为断言把它们钉住：同一批数据，只有 `is_qa` 不同，公开列表必须只返回
非 QA 的那一份，而管理员后台仍然要能看到 QA 数据。
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from server.helpcat.app import create_app
from server.helpcat.models import Cat, Community, Task


class PublicQaIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app("sqlite://", Path(self.tmp.name), fake_admin_openids={"admin-openid"})
        self.admin = self.login("admin-openid")
        self.admin_id = self.admin["user"]["id"]
        self.seed()

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self):
        """关键点：QA 行挂在 **ACTIVE** 小区上 —— 旧代码正是这样把它公开出去的。"""
        with self.app.state.session_factory() as db:
            db.add_all([
                # normalized_name 参与 (city, district, normalized_name) 唯一约束，
                # 直接建行时必须自己填，否则两行都是空串会撞唯一索引。
                Community(id="qa-live-community", street="银湖街道", name="公开小区",
                          normalized_name="gongkaixiaoqu",
                          status="ACTIVE", is_qa=False, created_by=self.admin_id),
                Community(id="qa-hidden-community", street="银湖街道", name="QA 小区",
                          normalized_name="qaxiaoxiaoqu",
                          status="ACTIVE", is_qa=True, created_by=self.admin_id),
            ])
            db.add_all([
                Cat(id="qa-live-cat", community_id="qa-live-community", code="C-LIVE", nickname="公开猫",
                    location_note="绿化带", review_status="APPROVED", visibility_status="ACTIVE",
                    is_qa=False, created_by=self.admin_id),
                Cat(id="qa-hidden-cat", community_id="qa-live-community", code="C-HIDDEN", nickname="QA 猫",
                    location_note="绿化带", review_status="APPROVED", visibility_status="ACTIVE",
                    is_qa=True, created_by=self.admin_id),
                Task(id="qa-live-task", title="公开任务", status="OPEN",
                     is_qa=False, created_by=self.admin_id),
                Task(id="qa-hidden-task", title="QA 任务", status="OPEN",
                     is_qa=True, created_by=self.admin_id),
            ])
            db.commit()

    def test_public_lists_never_expose_qa_rows(self):
        for path, expected, forbidden in (
            ("/api/v1/communities?limit=50", "公开小区", "QA 小区"),
            ("/api/v1/cats?limit=50", "公开猫", "QA 猫"),
            ("/api/v1/tasks?limit=50", "公开任务", "QA 任务"),
        ):
            status, body = self.request_on(self.app, "GET", path)
            self.assertEqual(status, 200, path)
            text = json.dumps(body, ensure_ascii=False)
            self.assertIn(expected, text, "%s 应包含非 QA 数据" % path)
            self.assertNotIn(forbidden, text, "%s 必须过滤掉 QA 数据" % path)

    def test_admin_session_still_sees_qa_rows(self):
        status, body = self.request_on(self.app, "GET", "/api/v1/cats?limit=50",
                                       token=self.admin["access_token"])
        self.assertEqual(status, 200)
        text = json.dumps(body, ensure_ascii=False)
        self.assertIn("QA 猫", text, "管理员后台仍要能看到 QA 数据（审核与清理都依赖它）")
        self.assertIn("公开猫", text)

    def test_public_cat_events_and_metrics_also_stay_qa_free(self):
        status, body = self.request_on(self.app, "GET", "/api/v1/cats/qa-hidden-cat/events")
        self.assertEqual(status, 404, "QA 猫咪的时间线不能公开")
        status, metrics = self.request_on(self.app, "GET", "/api/v1/public/metrics")
        self.assertEqual(status, 200)
        self.assertEqual(metrics, {"rescued": 0, "adopted": 0, "medical": 0, "supporters": 0})

    # ---- 脚手架（与其它 API 测试保持一致） --------------------------------

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

    def login(self, openid):
        status, body = self.request_on(self.app, "POST", "/api/v1/auth/wechat-login",
                                       payload={"code": "fake:" + openid})
        self.assertEqual(status, 200)
        return body


if __name__ == "__main__":
    unittest.main()
