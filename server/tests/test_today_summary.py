"""首页「今天就一件事 + 本周小结」的口径测试。

这个接口是首页唯一的动态数据源，两条口径最容易被写错，所以钉死：
  1. 覆盖判定 = 今天有值班认领（非 CANCELLED）**或**今天有投喂打卡；QA 数据一律不算。
  2. 周窗口 = 含今天在内的最近 7 天，和 /public/feeding-stats 同一个口径。
"""
import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from server.helpcat.app import create_app
from server.helpcat.models import Cat, Community, FeedingLog, FeedingPoint, FeedingShift


def shanghai_today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


class TodaySummaryApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app("sqlite://", Path(self.tmp.name), fake_admin_openids={"admin-openid"})
        self.admin = self.login(self.app, "admin-openid")
        self.user = self.login(self.app, "user-openid")
        self.admin_token = self.admin["access_token"]
        self.user_token = self.user["access_token"]
        self.user_id = self.user["user"]["id"]

    def tearDown(self):
        self.tmp.cleanup()

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
        return body

    # ---- 脚手架 --------------------------------------------------------

    def today(self):
        return self.request_on(self.app, "GET", "/api/v1/public/today")

    def create_point(self, **overrides):
        payload = {"name": "东门投喂点", "location_note": "东门树下", "feeding_time": "每天 18:00"}
        payload.update(overrides)
        status, body = self.request_on(
            self.app, "POST", "/api/v1/admin/feeding-points", token=self.admin_token, payload=payload,
        )
        self.assertEqual(status, 201, body)
        return body

    def check_in(self, point_id):
        status, body = self.request_on(
            self.app, "POST", "/api/v1/feeding-points/%s/logs" % point_id, token=self.user_token, payload={},
        )
        self.assertEqual(status, 201, body)
        return body

    def seed_log(self, point_id, fed_on, is_qa=False):
        with self.app.state.session_factory() as db:
            db.add(FeedingLog(point_id=point_id, user_id=self.user_id, fed_on=fed_on, is_qa=is_qa))
            db.commit()

    def seed_shift(self, point_id, shift_date, status="CLAIMED", is_qa=False):
        with self.app.state.session_factory() as db:
            db.add(FeedingShift(
                point_id=point_id, user_id=self.user_id, shift_date=shift_date, status=status, is_qa=is_qa,
            ))
            db.commit()

    def seed_cat(self, review_status="APPROVED", days_ago=0, is_qa=False):
        with self.app.state.session_factory() as db:
            # (city, district, normalized_name) 上有唯一约束，同一个小区只能建一次
            community = db.query(Community).first()
            if community is None:
                community = Community(street="银湖街道", name="银湖街道社区", status="APPROVED", created_by=self.user_id)
                db.add(community)
                db.flush()
            db.add(Cat(
                community_id=community.id, code="77-%s-%s" % (review_status, days_ago), nickname="77",
                location_note="东门", review_status=review_status, visibility_status="ACTIVE",
                created_by=self.user_id, is_qa=is_qa,
                created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            ))
            db.commit()

    def seed_impact(self, kind, days_ago=0, amount=1):
        occurred = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        status, body = self.request_on(
            self.app, "POST", "/api/v1/admin/impact-events", token=self.admin_token,
            payload={"kind": kind, "amount": amount, "occurred_at": occurred},
        )
        self.assertEqual(status, 201, body)

    # ---- 今天就一件事 --------------------------------------------------

    def test_empty_community_says_everything_is_covered(self):
        status, body = self.today()
        self.assertEqual(status, 200)
        self.assertEqual("quiet", body["headline"]["kind"])
        self.assertEqual(
            {"feeding": 0, "new_cats": 0, "rescued": 0, "adopted": 0, "medical": 0},
            {key: value for key, value in body["week"].items() if key != "since"},
        )
        self.assertEqual(shanghai_today(), body["date"])
        self.assertEqual(
            (datetime.fromisoformat(shanghai_today()).date() - timedelta(days=6)).isoformat(),
            body["week"]["since"],
            "since 是最近 7 天的起点（含今天），不是今天",
        )

    def test_uncovered_point_becomes_todays_one_thing(self):
        point = self.create_point()
        status, body = self.today()
        self.assertEqual("feeding_gap", body["headline"]["kind"])
        self.assertIn("1 个喂食点", body["headline"]["text"])
        self.assertIn(point["name"], body["headline"]["detail"])
        self.assertEqual("feeding", body["headline"]["action"])
        self.assertTrue(body["headline"]["action_label"])

    def test_check_in_today_clears_the_gap_and_a_task_takes_over(self):
        point = self.create_point()
        self.check_in(point["id"])
        _, body = self.today()
        self.assertNotEqual("feeding_gap", body["headline"]["kind"], "今天已打卡的点不该再被算作没人管")

        status, created = self.request_on(
            self.app, "POST", "/api/v1/tasks", token=self.admin_token,
            payload={"title": "带 77 去复查", "description": "需要有人陪同"},
        )
        self.assertEqual(status, 201, created)
        _, body = self.today()
        self.assertEqual("task_open", body["headline"]["kind"])
        self.assertEqual("tasks", body["headline"]["action"])

    def test_claim_or_cancelled_claim_and_qa_rows(self):
        point = self.create_point()
        self.seed_shift(point["id"], shanghai_today())
        _, body = self.today()
        self.assertNotEqual("feeding_gap", body["headline"]["kind"], "今天有人认领就算有人管")

        # 取消掉的认领不算覆盖
        with self.app.state.session_factory() as db:
            db.query(FeedingShift).delete()
            db.commit()
        self.seed_shift(point["id"], shanghai_today(), status="CANCELLED")
        _, body = self.today()
        self.assertEqual("feeding_gap", body["headline"]["kind"], "CANCELLED 的值班不能算覆盖")

        # QA 喂食点根本不参与（接口不接受 is_qa，只能直接落库）
        with self.app.state.session_factory() as db:
            db.add(FeedingPoint(
                name="QA 点", location_note="测试", created_by=self.user_id, is_qa=True, status="ACTIVE",
            ))
            db.commit()
        _, body = self.today()
        self.assertEqual(1, int(body["headline"]["text"].split(" ")[1]), "QA 点不能进公开数字")

    # ---- 本周小结 ------------------------------------------------------

    def test_week_window_only_counts_the_last_seven_days(self):
        point = self.create_point()
        self.check_in(point["id"])
        self.seed_log(point["id"], (datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=3)).isoformat())
        self.seed_log(point["id"], (datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=10)).isoformat())
        self.seed_impact("RESCUED", days_ago=0, amount=2)
        self.seed_impact("ADOPTED", days_ago=3, amount=1)
        self.seed_impact("MEDICAL", days_ago=10, amount=5)
        self.seed_cat(review_status="APPROVED", days_ago=1)
        self.seed_cat(review_status="PENDING_REVIEW", days_ago=1)

        _, body = self.today()
        week = body["week"]
        self.assertEqual(2, week["feeding"], "今天是第 1 次、3 天前是第 2 次，10 天前那次不算")
        self.assertEqual(2, week["rescued"])
        self.assertEqual(1, week["adopted"])
        self.assertEqual(0, week["medical"], "10 天前的医疗事件不该进本周")
        self.assertEqual(1, week["new_cats"], "只有已通过审核的档案才算新档案")

    def test_qa_and_pending_data_never_leaks_into_public_numbers(self):
        point = self.create_point()
        self.seed_log(point["id"], shanghai_today(), is_qa=True)
        self.seed_cat(review_status="APPROVED", days_ago=0, is_qa=True)
        _, body = self.today()
        self.assertEqual(0, body["week"]["feeding"], "QA 打卡不能进公开数字")
        self.assertEqual(0, body["week"]["new_cats"], "QA 档案不能进公开数字")

    def test_weekends_and_timezone_use_shanghai_calendar(self):
        """日历日必须按 Asia/Shanghai：投喂与值班都是这么记的。"""
        today = shanghai_today()
        self.assertEqual(today, self.today()[1]["date"])
        self.assertEqual(
            (datetime.fromisoformat(today).date() - timedelta(days=6)).isoformat(),
            self.today()[1]["week"]["since"],
        )


if __name__ == "__main__":
    unittest.main()
