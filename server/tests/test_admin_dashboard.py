"""后台看板的口径测试。

看板的每个数字都对应一个决策（今天有没有人管 / 积压多久 / 这周有没有人在动），
所以口径写错比算错更糟。这里钉住：埋点按天累加、白名单、覆盖率、最久等待天数、
欢迎页转化率、单人依赖度、以及"只有管理员能看"。
"""
import asyncio, json, os, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from server.helpcat.app import create_app
from server.helpcat.models import Cat, Community, FeedingLog, FeedingPoint, LeadMessage


class AdminDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app("sqlite://", Path(self.tmp.name), fake_admin_openids={"admin-openid"})
        self.admin = self.login("admin-openid")
        self.user = self.login("user-openid")
        self.admin_token = self.admin["access_token"]
        self.user_token = self.user["access_token"]
        self.user_id = self.user["user"]["id"]

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

        scope = {"type": "http", "http_version": "1.1", "method": method, "path": parsed.path,
                 "raw_path": parsed.path.encode(), "query_string": parsed.query.encode(),
                 "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                 "client": client, "server": ("testserver", 80), "scheme": "http"}
        await app(scope, receive, send)
        start = next(i for i in messages if i["type"] == "http.response.start")
        content = b"".join(i.get("body", b"") for i in messages if i["type"] == "http.response.body")
        return start["status"], (json.loads(content.decode()) if content else {})

    def request_on(self, method, path, token=None, payload=None):
        headers = {}
        if token:
            headers["Authorization"] = "Bearer " + token
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        return asyncio.run(self.asgi_request(self.app, method, path, headers, body))

    def login(self, openid):
        status, body = self.request_on("POST", "/api/v1/auth/wechat-login", payload={"code": "fake:" + openid})
        self.assertEqual(200, status, body)
        return body

    def dashboard(self, token=None):
        status, body = self.request_on("GET", "/api/v1/admin/dashboard", token=token or self.admin_token)
        self.assertEqual(200, status, body)
        return body

    def create_point(self, name="东门投喂点"):
        status, body = self.request_on("POST", "/api/v1/admin/feeding-points", token=self.admin_token,
                                       payload={"name": name, "location_note": "东门树下", "feeding_time": "每天 18:00"})
        self.assertEqual(201, status, body)
        return body

    def check_in(self, point_id):
        status, body = self.request_on("POST", "/api/v1/feeding-points/%s/logs" % point_id,
                                       token=self.user_token, payload={})
        self.assertEqual(201, status, body)

    def seed_cat(self, review_status="PENDING_REVIEW", with_photo=False, days_ago=0):
        from server.helpcat.models import MediaAsset
        with self.app.state.session_factory() as db:
            community = db.query(Community).first()
            if community is None:
                community = Community(street="银湖街道", name="银湖街道社区", status="APPROVED", created_by=self.user_id)
                db.add(community)
                db.flush()
            asset = None
            if with_photo:
                asset = MediaAsset(kind="CAT_PHOTO", path="x.webp", content_type="image/webp",
                                   byte_size=1, uploaded_by=self.user_id)
                db.add(asset)
                db.flush()
            db.add(Cat(community_id=community.id, code="c-%s-%s" % (review_status, days_ago), nickname="77",
                       location_note="东门", review_status=review_status, visibility_status="ACTIVE",
                       photo_asset_id=asset.id if asset else None, created_by=self.user_id,
                       created_at=datetime.now(timezone.utc) - timedelta(days=days_ago)))
            db.commit()

    def seed_lead(self):
        with self.app.state.session_factory() as db:
            db.add(LeadMessage(name="喜猫人", contact="wx-1", contact_type="WECHAT", message="想帮忙", status="NEW"))
            db.commit()

    # ---- 埋点 ----

    def test_visits_accumulate_per_day_and_reject_unknown_kinds(self):
        for _ in range(3):
            status, body = self.request_on("POST", "/api/v1/public/visit", payload={"kind": "home"})
            self.assertEqual(200, status, body)
        self.assertEqual(3, body["count"])
        status, _ = self.request_on("POST", "/api/v1/public/visit", payload={"kind": "admin"})
        self.assertEqual(400, status, "白名单外的 kind 必须拒绝，否则表会被垃圾行撑满")

    # ---- 今天的运营状态 ----

    def test_coverage_reflects_whether_anyone_covers_the_point_today(self):
        self.create_point()
        summary = self.dashboard()["today"]
        self.assertEqual(1, summary["feeding_points"])
        self.assertEqual(0, summary["covered"])
        self.assertEqual(0, summary["coverage_percent"])
        self.assertEqual(["东门投喂点"], summary["uncovered"])

        self.check_in(self.request_on("GET", "/api/v1/feeding-points")[1]["items"][0]["id"])
        summary = self.dashboard()["today"]
        self.assertEqual(1, summary["covered"])
        self.assertEqual(100, summary["coverage_percent"])
        self.assertEqual([], summary["uncovered"])

    def test_backlog_reports_counts_and_how_long_the_oldest_has_waited(self):
        self.seed_cat(days_ago=4)
        self.seed_cat(review_status="APPROVED", days_ago=0)
        self.seed_lead()
        summary = self.dashboard()["today"]
        self.assertEqual(1, summary["pending_cats"])
        self.assertGreaterEqual(summary["oldest_pending_days"], 4)
        self.assertEqual(1, summary["new_leads"])
        self.assertEqual(1, summary["cats_without_photo"], "没照片的公开档案要单独数出来")

    # ---- 本周趋势 ----

    def test_week_page_views_and_welcome_conversion(self):
        for _ in range(4):
            self.request_on("POST", "/api/v1/public/visit", payload={"kind": "welcome"})
        self.request_on("POST", "/api/v1/public/visit", payload={"kind": "home"})
        self.seed_lead()
        week = self.dashboard()["week"]
        self.assertEqual(4, week["page_views"]["welcome"])
        self.assertEqual(1, week["page_views"]["home"])
        self.assertEqual(5, week["page_views"]["total"])
        self.assertEqual(1, week["leads"])
        self.assertEqual(25, week["lead_conversion_percent"], "4 次欢迎页浏览留下 1 条 = 25%")

    def test_single_volunteer_dependency_is_visible(self):
        point = self.create_point()
        self.check_in(point["id"])
        week = self.dashboard()["week"]
        self.assertEqual(1, week["feeding_checkins"])
        self.assertEqual(1, week["active_volunteers"])
        self.assertEqual(100, week["top_volunteer_share_percent"], "只有一个人打卡 = 100% 依赖")

    # ---- 账户 / 设备 / 权限 ----

    def test_accounts_and_devices_summary(self):
        self.seed_cat(review_status="APPROVED")
        body = self.dashboard()
        self.assertGreaterEqual(body["accounts"]["total"], 2, "两个 fake 用户")
        self.assertEqual(1, body["accounts"]["admins"])
        self.assertTrue(body["accounts"]["recent"])
        self.assertGreaterEqual(body["devices"]["active"], 2)
        self.assertEqual(0, body["devices"]["legacy"], "这批会话都带 SESSION_ISSUE 审计")

    def test_dashboard_is_admin_only(self):
        status, body = self.request_on("GET", "/api/v1/admin/dashboard", token=self.user_token)
        self.assertEqual(403, status, body)


if __name__ == "__main__":
    unittest.main()
