import asyncio
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import select

from server.helpcat.app import create_app
from server.helpcat.models import AuditLog, FeedingShift, User


def shanghai_today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def day(offset=0):
    return (date.fromisoformat(shanghai_today()) + timedelta(days=offset)).isoformat()


class FeedingShiftApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = self.build_app(Path(self.tmp.name))
        self.admin = self.login(self.app, "admin-openid")
        self.admin_token = self.admin["access_token"]
        self.user = self.login(self.app, "user-openid")
        self.user_token = self.user["access_token"]
        self.user_id = self.user["user"]["id"]
        self.other = self.login(self.app, "other-openid")
        self.other_token = self.other["access_token"]

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

    def claim(self, point_id, shift_date=None, token=None, **overrides):
        payload = {"shift_date": shift_date or shanghai_today()}
        payload.update(overrides)
        return self.request_on(
            self.app, "POST", "/api/v1/feeding-points/%s/shifts" % point_id,
            token=token or self.user_token, payload=payload,
        )

    def release(self, shift_id, token=None):
        return self.request_on(
            self.app, "POST", "/api/v1/feeding-shifts/%s/release" % shift_id,
            token=token if token is not None else self.user_token,
        )

    def public_list(self, query="", token=None):
        return self.request_on(self.app, "GET", "/api/v1/feeding-shifts" + query, token=token)

    def check_in(self, point_id, token=None):
        return self.request_on(
            self.app, "POST", "/api/v1/feeding-points/%s/logs" % point_id,
            token=token or self.user_token, payload={},
        )

    def my_shifts(self, token=None, query=""):
        return self.request_on(
            self.app, "GET", "/api/v1/feeding-shifts/mine" + query,
            token=token if token is not None else self.user_token,
        )

    def set_nickname(self, user_id, nickname):
        with self.app.state.session_factory() as db:
            db.get(User, user_id).nickname = nickname
            db.commit()

    def seed_shift(self, point_id, user_id, shift_date, status="CLAIMED"):
        with self.app.state.session_factory() as db:
            item = FeedingShift(point_id=point_id, user_id=user_id, shift_date=shift_date, status=status)
            db.add(item)
            db.commit()
            return item.id

    # ---- 公开排班 ------------------------------------------------------

    def test_anonymous_can_read_the_public_schedule(self):
        point = self.create_point()[1]
        shift = self.claim(point["id"])[1]

        status, body = self.public_list()
        self.assertEqual(status, 200)
        self.assertEqual(body["from"], shanghai_today())
        self.assertEqual(body["days"], 7)
        self.assertEqual(body["today"], shanghai_today())
        self.assertEqual(len(body["items"]), 1)
        item = body["items"][0]
        self.assertEqual(item["id"], shift["id"])
        self.assertEqual(item["point_id"], point["id"])
        self.assertEqual(item["point_name"], "东门投喂点")
        self.assertEqual(item["shift_date"], shanghai_today())
        self.assertEqual(item["status"], "CLAIMED")
        self.assertEqual(item["note"], "")
        self.assertFalse(item["is_mine"])
        self.assertEqual(item["user_label"], "志愿者")

    def test_the_window_is_bounded_and_validated(self):
        status, body = self.public_list("?from=not-a-date")
        self.assertEqual(status, 422)
        self.assertEqual(body["code"], "invalid_shift_date")

        self.assertEqual(self.public_list("?days=15")[0], 422)
        self.assertEqual(self.public_list("?days=0")[0], 422)
        self.assertEqual(self.public_list("?from=2025-13-40")[0], 422)

        status, body = self.public_list("?from=%s&days=14" % day(1))
        self.assertEqual(status, 200)
        self.assertEqual(body["from"], day(1))
        self.assertEqual(body["days"], 14)

    def test_shifts_are_ordered_by_date_then_point_name(self):
        later = self.create_point(name="B 点")[1]
        earlier = self.create_point(name="A 点")[1]
        self.claim(later["id"], day(2))
        self.claim(earlier["id"], day(2))
        self.claim(earlier["id"], day(0))

        status, body = self.public_list()
        self.assertEqual(status, 200)
        self.assertEqual(
            [(item["shift_date"], item["point_name"]) for item in body["items"]],
            [(day(0), "A 点"), (day(2), "A 点"), (day(2), "B 点")],
        )

    # ---- 认领 ----------------------------------------------------------

    def test_a_volunteer_claims_today_and_every_day_up_to_the_limit(self):
        point = self.create_point()[1]
        status, body = self.claim(point["id"], day(0))
        self.assertEqual(status, 201)
        self.assertEqual(body["shift_date"], day(0))
        self.assertEqual(body["status"], "CLAIMED")
        self.assertTrue(body["is_mine"])

        another = self.create_point(name="西门投喂点")[1]
        status, body = self.claim(another["id"], day(13))
        self.assertEqual(status, 201)
        self.assertEqual(body["shift_date"], day(13))

        third = self.create_point(name="北门投喂点")[1]
        status, body = self.claim(third["id"], day(14))
        self.assertEqual(status, 422)
        self.assertEqual(body["code"], "shift_date_out_of_range")

        status, _ = self.claim(third["id"], day(-1))
        self.assertEqual(status, 422)

        status, _ = self.claim(third["id"], "2025-13-40")
        self.assertEqual(status, 422)
        status, _ = self.claim(third["id"], "2025-1-1")
        self.assertEqual(status, 422)
        status, _ = self.claim(third["id"], "tomorrow")
        self.assertEqual(status, 422)

    def test_claiming_an_unknown_or_inactive_point_is_not_found(self):
        status, body = self.claim("does-not-exist")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "feeding_point_not_found")

        point = self.create_point()[1]
        self.patch_point(point["id"], status="PAUSED")
        status, body = self.claim(point["id"])
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "feeding_point_not_found")

    def test_reclaiming_the_same_slot_is_idempotent_and_conflicts_across_volunteers(self):
        point = self.create_point()[1]
        first = self.claim(point["id"], note="第一次")[1]

        status, again = self.claim(point["id"], note="再来一次")
        self.assertEqual(status, 200)
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(again["note"], "第一次")

        status, body = self.claim(point["id"], token=self.other_token)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "shift_already_claimed")

        with self.app.state.session_factory() as db:
            rows = db.scalars(select(FeedingShift).where(FeedingShift.point_id == point["id"])).all()
        self.assertEqual(len(rows), 1)

    def test_a_released_slot_can_be_claimed_by_someone_else(self):
        point = self.create_point()[1]
        shift = self.claim(point["id"])[1]

        status, body = self.release(shift["id"])
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "CANCELLED")

        # The cancelled row leaves the public grid so the day looks free again.
        status, body = self.public_list()
        self.assertEqual(status, 200)
        self.assertEqual(body["items"], [])

        status, claimed = self.claim(point["id"], token=self.other_token)
        self.assertEqual(status, 201)
        self.assertEqual(claimed["status"], "CLAIMED")
        self.assertNotEqual(claimed["id"], shift["id"])

        status, body = self.public_list()
        self.assertEqual(status, 200)
        self.assertEqual(
            [(item["id"], item["status"]) for item in body["items"]],
            [(claimed["id"], "CLAIMED")],
        )

    def test_a_cancelled_row_never_returns_as_done_after_a_check_in(self):
        point = self.create_point()[1]
        shift = self.claim(point["id"])[1]
        self.assertEqual(self.release(shift["id"])[0], 200)

        # Checking in without a live claim still logs the feed, but it must not
        # resurrect the cancelled row.
        status, _ = self.check_in(point["id"])
        self.assertEqual(status, 201)
        with self.app.state.session_factory() as db:
            self.assertEqual(db.get(FeedingShift, shift["id"]).status, "CANCELLED")
        self.assertEqual(self.public_list()[1]["items"], [])

    # ---- 释放 ----------------------------------------------------------

    def test_only_the_claimer_or_an_admin_releases_a_slot(self):
        point = self.create_point()[1]
        shift = self.claim(point["id"])[1]

        status, body = self.release(shift["id"], token=self.other_token)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "forbidden")
        self.assertEqual(self.public_list()[1]["items"][0]["status"], "CLAIMED")

        status, body = self.release(shift["id"], token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "CANCELLED")

        status, body = self.release("does-not-exist")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "feeding_shift_not_found")

    def test_cancelled_and_done_shifts_follow_the_release_rules(self):
        point = self.create_point()[1]
        shift = self.claim(point["id"])[1]
        self.release(shift["id"])
        status, body = self.release(shift["id"])
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "shift_already_cancelled")

        done_point = self.create_point(name="北门投喂点")[1]
        done = self.claim(done_point["id"])[1]
        self.assertEqual(self.check_in(done_point["id"])[0], 201)

        status, body = self.release(done["id"])
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "shift_done_locked")

        status, body = self.release(done["id"], token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "CANCELLED")

    # ---- 隐私 ----------------------------------------------------------

    def test_labels_are_masked_and_is_mine_follows_the_caller(self):
        point = self.create_point()[1]
        self.set_nickname(self.user_id, "张阿姨")
        claim = self.claim(point["id"])[1]
        self.assertEqual(claim["user_label"], "张**")
        self.assertTrue(claim["is_mine"])
        self.assertNotIn("张阿姨", json.dumps(claim, ensure_ascii=False))

        status, mine = self.public_list(token=self.user_token)
        self.assertEqual(status, 200)
        self.assertTrue(mine["items"][0]["is_mine"])
        self.assertEqual(mine["items"][0]["user_label"], "张**")

        status, theirs = self.public_list(token=self.other_token)
        self.assertEqual(status, 200)
        self.assertFalse(theirs["items"][0]["is_mine"])
        self.assertEqual(theirs["items"][0]["user_label"], "张**")
        self.assertNotIn("张阿姨", json.dumps(theirs, ensure_ascii=False))
        self.assertNotIn("openid", json.dumps(theirs))

        status, anonymous = self.public_list()
        self.assertEqual(status, 200)
        self.assertFalse(anonymous["items"][0]["is_mine"])
        self.assertNotIn("张阿姨", json.dumps(anonymous, ensure_ascii=False))

    # ---- 打卡联动与范围 ------------------------------------------------

    def test_checking_in_marks_todays_claimed_shift_done(self):
        point = self.create_point()[1]
        shift = self.claim(point["id"])[1]

        status, _ = self.check_in(point["id"])
        self.assertEqual(status, 201)
        with self.app.state.session_factory() as db:
            self.assertEqual(db.get(FeedingShift, shift["id"]).status, "DONE")

        status, body = self.public_list(token=self.user_token)
        self.assertEqual(status, 200)
        self.assertEqual(body["items"][0]["status"], "DONE")

    def test_a_shift_on_an_inactive_point_leaves_the_public_list(self):
        point = self.create_point()[1]
        shift = self.claim(point["id"])[1]
        self.assertEqual(len(self.public_list()[1]["items"]), 1)

        self.patch_point(point["id"], status="PAUSED")
        self.assertEqual(self.public_list()[1]["items"], [])

        self.patch_point(point["id"], status="ARCHIVED")
        self.assertEqual(self.public_list()[1]["items"], [])

        status, body = self.release(shift["id"])
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "CANCELLED")

    # ---- 我的排班 ------------------------------------------------------

    def test_my_shifts_lists_only_my_upcoming_claims(self):
        point = self.create_point()[1]
        other_point = self.create_point(name="西门投喂点")[1]
        mine = self.claim(point["id"], day(2))[1]
        self.claim(other_point["id"], day(1), token=self.other_token)
        self.seed_shift(point["id"], self.user_id, day(-1))

        status, body = self.my_shifts()
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in body["items"]], [mine["id"]])
        self.assertEqual(body["items"][0]["point_name"], "东门投喂点")
        self.assertEqual(body["items"][0]["shift_date"], day(2))
        self.assertTrue(body["items"][0]["is_mine"])

        status, _ = self.request_on(self.app, "GET", "/api/v1/feeding-shifts/mine")
        self.assertEqual(status, 401)

    # ---- 审计 ----------------------------------------------------------

    def test_claim_and_release_write_audit_rows(self):
        point = self.create_point()[1]
        shift = self.claim(point["id"])[1]
        with self.app.state.session_factory() as db:
            logs = db.scalars(select(AuditLog).where(
                AuditLog.entity_type == "feeding_shift", AuditLog.entity_id == shift["id"],
            )).all()
        self.assertEqual([log.action for log in logs], ["CREATE"])
        after = json.loads(logs[0].after_json)
        self.assertEqual(after["status"], "CLAIMED")
        self.assertEqual(after["point_id"], point["id"])
        self.assertEqual(after["shift_date"], shanghai_today())

        self.release(shift["id"])
        with self.app.state.session_factory() as db:
            logs = db.scalars(select(AuditLog).where(
                AuditLog.entity_type == "feeding_shift", AuditLog.entity_id == shift["id"],
            )).all()
        self.assertEqual(sorted(log.action for log in logs), ["CREATE", "UPDATE"])
        updates = [log for log in logs if log.action == "UPDATE"]
        self.assertEqual(json.loads(updates[0].before_json)["status"], "CLAIMED")
        self.assertEqual(json.loads(updates[0].after_json)["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
