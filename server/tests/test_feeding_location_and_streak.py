import asyncio
import json
import math
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from server.helpcat.app import create_app
from server.helpcat.models import FeedingLog


def shanghai_today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def haversine_distance_m(lat1, lng1, lat2, lng2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lng / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


class FeedingLocationAndStreakApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = self.build_app(Path(self.tmp.name))
        self.admin = self.login(self.app, "admin-openid")
        self.user = self.login(self.app, "user-openid")
        self.admin_token = self.admin["access_token"]
        self.user_token = self.user["access_token"]
        self.user_id = self.user["user"]["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def build_app(self, storage_root, **environment):
        with mock.patch.dict(os.environ, dict(environment), clear=False):
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
        return body

    # ---- 脚手架 --------------------------------------------------------

    def create_point(self, **overrides):
        payload = {"name": "东门投喂点", "location_note": "东门树下", "feeding_time": "每天 18:00"}
        payload.update(overrides)
        return self.request_on(self.app, "POST", "/api/v1/admin/feeding-points", token=self.admin_token, payload=payload)

    def patch_point(self, point_id, **payload):
        return self.request_on(
            self.app, "PATCH", "/api/v1/admin/feeding-points/%s" % point_id,
            token=self.admin_token, payload=payload,
        )

    def check_in(self, point_id, token=None):
        return self.request_on(
            self.app, "POST", "/api/v1/feeding-points/%s/logs" % point_id,
            token=token or self.user_token, payload={},
        )

    def seed_log(self, point_id, fed_on, user_id=None, is_qa=False):
        """Write a past-dated check-in directly; the endpoint only ever writes today."""
        with self.app.state.session_factory() as db:
            item = FeedingLog(
                point_id=point_id, user_id=user_id or self.user_id, fed_on=fed_on, is_qa=is_qa,
            )
            db.add(item)
            db.commit()
            return item.id

    def summary(self, token=None):
        return self.request_on(
            self.app, "GET", "/api/v1/feeding-logs/mine/summary", token=token if token is not None else self.user_token,
        )

    # ---- 坐标与距离 ----------------------------------------------------

    def test_creating_a_point_with_coordinates_returns_them_and_needs_feed(self):
        status, body = self.create_point(latitude=30.05, longitude=119.95)
        self.assertEqual(status, 201)
        self.assertEqual(body["latitude"], 30.05)
        self.assertEqual(body["longitude"], 119.95)
        self.assertIsNone(body["distance_m"])
        self.assertTrue(body["needs_feed"])

        status, body = self.create_point(name="无坐标点")
        self.assertEqual(status, 201)
        self.assertIsNone(body["latitude"])
        self.assertIsNone(body["longitude"])
        self.assertTrue(body["needs_feed"])

    def test_coordinates_outside_the_valid_range_are_rejected(self):
        status, _ = self.create_point(latitude=120, longitude=119.95)
        self.assertEqual(status, 422)
        status, _ = self.create_point(latitude=30.05, longitude=-400)
        self.assertEqual(status, 422)

    def test_distance_ordering_puts_nearby_first_and_unlocated_last(self):
        nearby = self.create_point(name="近点", latitude=30.001, longitude=120.001)[1]
        far = self.create_point(name="远点", latitude=31.0, longitude=121.0)[1]
        unlocated = self.create_point(name="无坐标点")[1]

        status, body = self.request_on(self.app, "GET", "/api/v1/feeding-points?lat=30.0&lng=120.0")
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in body["items"]], [nearby["id"], far["id"], unlocated["id"]])
        self.assertIsNone(body["next_cursor"])

        expected_nearby = round(haversine_distance_m(30.0, 120.0, 30.001, 120.001))
        expected_far = round(haversine_distance_m(30.0, 120.0, 31.0, 121.0))
        self.assertAlmostEqual(body["items"][0]["distance_m"], expected_nearby, delta=2)
        self.assertAlmostEqual(body["items"][1]["distance_m"], expected_far, delta=2)
        self.assertLess(body["items"][0]["distance_m"], body["items"][1]["distance_m"])
        self.assertIsNone(body["items"][2]["distance_m"])

    def test_sort_today_puts_an_unfed_point_before_a_fed_one(self):
        unfed = self.create_point(name="待投喂点")[1]
        fed = self.create_point(name="已投喂点")[1]
        self.assertEqual(self.check_in(fed["id"])[0], 201)

        status, body = self.request_on(self.app, "GET", "/api/v1/feeding-points?sort=today")
        self.assertEqual(status, 200)
        self.assertEqual(body["items"][0]["id"], unfed["id"])
        self.assertTrue(body["items"][0]["needs_feed"])
        self.assertIsNone(body["next_cursor"])
        listed = {item["id"]: item for item in body["items"]}
        self.assertEqual(set(listed), {unfed["id"], fed["id"]})
        self.assertFalse(listed[fed["id"]]["needs_feed"])
        self.assertEqual(listed[fed["id"]]["fed_today"], 1)

    def test_edit_can_set_coordinates_later_and_leaves_them_when_omitted(self):
        point = self.create_point()[1]
        self.assertIsNone(point["latitude"])
        self.assertIsNone(point["longitude"])

        status, body = self.patch_point(point["id"], latitude=30.1, longitude=120.2)
        self.assertEqual(status, 200)
        self.assertEqual(body["latitude"], 30.1)
        self.assertEqual(body["longitude"], 120.2)

        status, body = self.patch_point(point["id"], feeding_time="每天 07:00")
        self.assertEqual(status, 200)
        self.assertEqual(body["feeding_time"], "每天 07:00")
        self.assertEqual(body["latitude"], 30.1)
        self.assertEqual(body["longitude"], 120.2)

        status, _ = self.patch_point(point["id"], latitude=120)
        self.assertEqual(status, 422)

    # ---- 打卡进度 ------------------------------------------------------

    def test_summary_requires_a_login(self):
        status, body = self.request_on(self.app, "GET", "/api/v1/feeding-logs/mine/summary")
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "unauthorized")

    def test_summary_without_logs_is_empty_and_offers_the_first_milestone(self):
        status, body = self.summary()
        self.assertEqual(status, 200)
        self.assertFalse(body["checked_in_today"])
        self.assertEqual(body["streak_days"], 0)
        self.assertEqual(body["next_milestone"], 3)
        self.assertEqual(body["days_this_week"], 0)
        self.assertEqual(body["total_days"], 0)
        self.assertIsNone(body["last_fed_on"])
        self.assertEqual(body["points_checked_today"], 0)

    def test_summary_after_one_log_today_starts_a_one_day_streak(self):
        point = self.create_point()[1]
        self.assertEqual(self.check_in(point["id"])[0], 201)
        status, body = self.summary()
        self.assertEqual(status, 200)
        self.assertTrue(body["checked_in_today"])
        self.assertEqual(body["streak_days"], 1)
        self.assertEqual(body["next_milestone"], 3)
        self.assertEqual(body["days_this_week"], 1)
        self.assertEqual(body["total_days"], 1)
        self.assertEqual(body["last_fed_on"], shanghai_today().isoformat())
        self.assertEqual(body["points_checked_today"], 1)

    def test_summary_counts_consecutive_days_and_advances_the_milestone(self):
        point = self.create_point()[1]
        today = shanghai_today()
        for offset in (0, 1, 2):
            self.seed_log(point["id"], (today - timedelta(days=offset)).isoformat())
        status, body = self.summary()
        self.assertEqual(status, 200)
        self.assertEqual(body["streak_days"], 3)
        self.assertEqual(body["next_milestone"], 7)
        self.assertEqual(body["total_days"], 3)
        self.assertEqual(body["days_this_week"], 3)
        self.assertEqual(body["last_fed_on"], today.isoformat())

    def test_summary_streak_still_counts_from_yesterday_when_today_is_missed(self):
        point = self.create_point()[1]
        yesterday = (shanghai_today() - timedelta(days=1)).isoformat()
        self.seed_log(point["id"], yesterday)
        status, body = self.summary()
        self.assertEqual(status, 200)
        self.assertFalse(body["checked_in_today"])
        self.assertEqual(body["streak_days"], 1)
        self.assertEqual(body["next_milestone"], 3)
        self.assertEqual(body["total_days"], 1)
        self.assertEqual(body["last_fed_on"], yesterday)

    def test_summary_streak_breaks_after_a_whole_missed_day(self):
        point = self.create_point()[1]
        two_days_ago = (shanghai_today() - timedelta(days=2)).isoformat()
        self.seed_log(point["id"], two_days_ago)
        status, body = self.summary()
        self.assertEqual(status, 200)
        self.assertFalse(body["checked_in_today"])
        self.assertEqual(body["streak_days"], 0)
        self.assertEqual(body["next_milestone"], 3)
        self.assertEqual(body["total_days"], 1)
        self.assertEqual(body["days_this_week"], 1)
        self.assertEqual(body["last_fed_on"], two_days_ago)

    def test_summary_counts_distinct_days_and_points_today(self):
        first = self.create_point(name="A 点")[1]
        second = self.create_point(name="B 点")[1]
        today = shanghai_today()
        self.seed_log(first["id"], today.isoformat())
        self.seed_log(second["id"], today.isoformat())
        self.seed_log(second["id"], (today - timedelta(days=2)).isoformat())
        self.seed_log(second["id"], (today - timedelta(days=8)).isoformat())

        status, body = self.summary()
        self.assertEqual(status, 200)
        self.assertEqual(body["points_checked_today"], 2)
        self.assertEqual(body["total_days"], 3)
        self.assertEqual(body["days_this_week"], 2)
        self.assertEqual(body["streak_days"], 1)
        self.assertTrue(body["checked_in_today"])

    def test_summary_ignores_qa_logs(self):
        point = self.create_point()[1]
        today = shanghai_today()
        self.seed_log(point["id"], today.isoformat(), is_qa=True)
        status, body = self.summary()
        self.assertEqual(status, 200)
        self.assertFalse(body["checked_in_today"])
        self.assertEqual(body["streak_days"], 0)
        self.assertEqual(body["total_days"], 0)
        self.assertEqual(body["points_checked_today"], 0)


if __name__ == "__main__":
    unittest.main()
