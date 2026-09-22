import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import select

from server.helpcat.app import create_app
from server.helpcat.models import AuditLog, Cat, Community, FeedingLog, Task, User


def shanghai_today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


class FeedingAndTaskClosureApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = self.build_app(Path(self.tmp.name))
        self.admin = self.login(self.app, "admin-openid")
        self.user = self.login(self.app, "user-openid")
        self.other = self.login(self.app, "other-openid")
        self.admin_token = self.admin["access_token"]
        self.user_token = self.user["access_token"]
        self.other_token = self.other["access_token"]
        self.admin_id = self.admin["user"]["id"]
        self.user_id = self.user["user"]["id"]
        self.other_id = self.other["user"]["id"]

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
        payload = {
            "name": "东门投喂点", "community_id": None, "location_note": "东门树下",
            "feeding_time": "每天 18:00", "caretaker_note": "阿姨负责",
        }
        payload.update(overrides)
        return self.request_on(self.app, "POST", "/api/v1/admin/feeding-points", token=self.admin_token, payload=payload)

    def patch_point(self, point_id, token=None, **payload):
        return self.request_on(
            self.app, "PATCH", "/api/v1/admin/feeding-points/%s" % point_id,
            token=token or self.admin_token, payload=payload,
        )

    def check_in(self, point_id, token=None, **payload):
        return self.request_on(
            self.app, "POST", "/api/v1/feeding-points/%s/logs" % point_id,
            token=token or self.user_token, payload=payload,
        )

    def create_task(self, **overrides):
        payload = {"title": "搬运猫粮", "description": "把猫粮搬到仓库", "community_id": None}
        payload.update(overrides)
        return self.request_on(self.app, "POST", "/api/v1/tasks", token=self.admin_token, payload=payload)

    def claim_task(self, task_id, token=None):
        return self.request_on(
            self.app, "POST", "/api/v1/tasks/%s/claim" % task_id, token=token or self.user_token,
        )

    def complete_task(self, task_id, token=None, **payload):
        return self.request_on(
            self.app, "POST", "/api/v1/tasks/%s/complete" % task_id,
            token=token or self.user_token, payload=payload,
        )

    def cancel_task(self, task_id, token=None, **payload):
        return self.request_on(
            self.app, "POST", "/api/v1/tasks/%s/cancel" % task_id,
            token=token or self.admin_token, payload=payload,
        )

    def reassign_task(self, task_id, token=None, target_user_id=None):
        return self.request_on(
            self.app, "POST", "/api/v1/tasks/%s/reassign" % task_id,
            token=token or self.admin_token, payload={"target_user_id": target_user_id},
        )

    def create_cat_event(self, cat_id, token=None, **overrides):
        payload = {"kind": "NOTE", "title": "近况", "detail": "", "occurred_at": None}
        payload.update(overrides)
        return self.request_on(
            self.app, "POST", "/api/v1/admin/cats/%s/events" % cat_id, token=token or self.admin_token, payload=payload,
        )

    def seed_community(self, community_id="community-1", name="星河家园", status="ACTIVE"):
        with self.app.state.session_factory() as db:
            admin = db.scalar(select(User).where(User.openid == "admin-openid"))
            db.add(Community(
                id=community_id, name=name, normalized_name=name, street="银湖街道",
                status=status, created_by=admin.id,
            ))
            db.commit()
        return community_id

    def seed_cat(self, cat_id="cat-timeline", code="HC-TIMELINE", review_status="APPROVED",
                 visibility_status="ACTIVE", community_id="community-timeline",
                 community_name="时间线小区", community_status="ACTIVE"):
        with self.app.state.session_factory() as db:
            admin = db.scalar(select(User).where(User.openid == "admin-openid"))
            if not db.get(Community, community_id):
                db.add(Community(
                    id=community_id, name=community_name, normalized_name=community_name,
                    street="银湖街道", status=community_status, created_by=admin.id,
                ))
                db.flush()
            db.add(Cat(
                id=cat_id, community_id=community_id, code=code, nickname="测试猫",
                location_note="北门", review_status=review_status,
                visibility_status=visibility_status, created_by=admin.id,
            ))
            db.commit()
        return cat_id

    # ---- 定点投喂 ------------------------------------------------------

    def test_admin_creates_a_feeding_point(self):
        status, body = self.create_point()
        self.assertEqual(status, 201)
        self.assertEqual(body["name"], "东门投喂点")
        self.assertIsNone(body["community_id"])
        self.assertEqual(body["community_name"], "")
        self.assertEqual(body["location_note"], "东门树下")
        self.assertEqual(body["feeding_time"], "每天 18:00")
        self.assertEqual(body["caretaker_note"], "阿姨负责")
        self.assertEqual(body["status"], "ACTIVE")
        self.assertEqual(body["fed_today"], 0)
        self.assertFalse(body["fed_by_me"])
        self.assertIsNone(body["last_fed_at"])

        status, body = self.request_on(
            self.app, "POST", "/api/v1/admin/feeding-points", token=self.user_token, payload={"name": "无权限"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "forbidden")

    def test_a_feeding_point_can_be_linked_to_an_active_community(self):
        community_id = self.seed_community()
        status, body = self.create_point(community_id=community_id)
        self.assertEqual(status, 201)
        self.assertEqual(body["community_id"], community_id)
        # 创建接口与列表接口都会解析 community_name。
        self.assertEqual(body["community_name"], "星河家园")

        status, body = self.create_point(name="无效小区", community_id="missing-community")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "community_not_found")

        status, listed = self.request_on(
            self.app, "GET", "/api/v1/admin/feeding-points?status=ACTIVE", token=self.admin_token,
        )
        self.assertEqual(status, 200)
        linked = next(item for item in listed["items"] if item["community_id"] == community_id)
        self.assertEqual(linked["community_name"], "星河家园")

    def test_admin_edits_a_feeding_point_and_rejects_an_unknown_status(self):
        point = self.create_point()[1]
        status, body = self.patch_point(point["id"], status="PAUSED", feeding_time="每天 07:00")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "PAUSED")
        self.assertEqual(body["feeding_time"], "每天 07:00")
        self.assertEqual(body["name"], "东门投喂点")

        status, _ = self.patch_point(point["id"], status="DISABLED")
        self.assertEqual(status, 422)

        status, body = self.patch_point("does-not-exist", status="ACTIVE")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "feeding_point_not_found")

        status, body = self.patch_point(point["id"], token=self.user_token, status="ACTIVE")
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "forbidden")

    def test_admin_lists_every_point_while_the_public_list_shows_only_active(self):
        active = self.create_point(name="A 点")[1]
        second = self.create_point(name="B 点")[1]
        paused = self.create_point(name="P 点")[1]
        self.assertEqual(self.patch_point(paused["id"], status="PAUSED")[0], 200)

        status, body = self.request_on(self.app, "GET", "/api/v1/feeding-points")
        self.assertEqual(status, 200)
        self.assertEqual({item["id"] for item in body["items"]}, {active["id"], second["id"]})
        self.assertNotIn(paused["id"], {item["id"] for item in body["items"]})
        self.assertIn("fed_today", body["items"][0])
        self.assertIn("fed_by_me", body["items"][0])

        status, body = self.request_on(self.app, "GET", "/api/v1/admin/feeding-points", token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual({item["id"] for item in body["items"]}, {active["id"], second["id"], paused["id"]})

        status, body = self.request_on(self.app, "GET", "/api/v1/admin/feeding-points?status=PAUSED", token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in body["items"]], [paused["id"]])

        status, first_page = self.request_on(self.app, "GET", "/api/v1/feeding-points?limit=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(first_page["items"]), 1)
        self.assertIsNotNone(first_page["next_cursor"])
        status, second_page = self.request_on(
            self.app, "GET", "/api/v1/feeding-points?limit=1&cursor=" + first_page["next_cursor"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(second_page["items"]), 1)
        self.assertNotEqual(first_page["items"][0]["id"], second_page["items"][0]["id"])
        self.assertEqual(
            {first_page["items"][0]["id"], second_page["items"][0]["id"]},
            {active["id"], second["id"]},
        )

        status, body = self.request_on(self.app, "GET", "/api/v1/admin/feeding-points", token=self.user_token)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "forbidden")

    def test_a_volunteer_checks_in_once_per_day_and_sees_the_log_in_mine(self):
        point = self.create_point()[1]
        status, first = self.check_in(point["id"], food_note="猫粮 200g", note="两只猫", photo_asset_id=None)
        self.assertEqual(status, 201)
        self.assertEqual(first["point_id"], point["id"])
        self.assertEqual(first["point_name"], "东门投喂点")
        self.assertEqual(first["user_id"], self.user_id)
        self.assertEqual(first["fed_on"], shanghai_today())
        self.assertEqual(first["food_note"], "猫粮 200g")
        self.assertEqual(first["note"], "两只猫")
        self.assertIsNone(first["photo_asset_id"])
        self.assertIsNotNone(first["fed_at"])

        status, second = self.check_in(point["id"], food_note="再喂一次")
        self.assertEqual(status, 201)
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["food_note"], "猫粮 200g")
        with self.app.state.session_factory() as db:
            self.assertEqual(len(db.scalars(select(FeedingLog)).all()), 1)

        status, body = self.request_on(self.app, "GET", "/api/v1/feeding-logs/mine", token=self.user_token)
        self.assertEqual(status, 200)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["id"], first["id"])
        self.assertEqual(body["items"][0]["point_name"], "东门投喂点")

        status, body = self.request_on(self.app, "GET", "/api/v1/feeding-points")
        self.assertEqual(body["items"][0]["fed_today"], 1)
        self.assertFalse(body["items"][0]["fed_by_me"])
        status, body = self.request_on(self.app, "GET", "/api/v1/feeding-points", token=self.user_token)
        self.assertTrue(body["items"][0]["fed_by_me"])
        status, body = self.request_on(self.app, "GET", "/api/v1/feeding-points", token=self.other_token)
        self.assertFalse(body["items"][0]["fed_by_me"])

        status, body = self.request_on(self.app, "GET", "/api/v1/feeding-logs/mine")
        self.assertEqual(status, 401)

    def test_a_paused_or_unknown_point_rejects_check_ins(self):
        active = self.create_point(name="正常点")[1]
        paused = self.create_point(name="暂停点")[1]
        self.assertEqual(self.patch_point(paused["id"], status="PAUSED")[0], 200)

        status, body = self.check_in(paused["id"])
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "feeding_point_not_found")

        status, body = self.check_in("missing-point")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "feeding_point_not_found")

        status, body = self.request_on(
            self.app, "POST", "/api/v1/feeding-points/%s/logs" % active["id"], payload={},
        )
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "unauthorized")

    def test_public_feeding_stats_report_live_volunteers(self):
        active = self.create_point(name="统计点")[1]
        paused = self.create_point(name="暂停统计点")[1]
        self.assertEqual(self.patch_point(paused["id"], status="PAUSED")[0], 200)

        self.assertEqual(self.check_in(active["id"])[0], 201)
        self.assertEqual(self.check_in(active["id"], token=self.other_token)[0], 201)

        status, body = self.request_on(self.app, "GET", "/api/v1/public/feeding-stats")
        self.assertEqual(status, 200)
        self.assertEqual(body["points_active"], 1)
        self.assertEqual(body["feeds_today"], 2)
        self.assertEqual(body["feeds_week"], 2)
        self.assertEqual(body["volunteers_week"], 2)
        self.assertIsNotNone(body["last_fed_at"])
        self.assertEqual(body["today"], shanghai_today())

    # ---- 任务闭环 ------------------------------------------------------

    def test_public_lists_only_open_tasks_and_a_volunteer_can_claim_one(self):
        task = self.create_task()[1]
        self.assertEqual(task["title"], "搬运猫粮")
        self.assertEqual(task["status"], "OPEN")
        self.assertIsNone(task["claimed_by"])

        status, body = self.request_on(self.app, "GET", "/api/v1/tasks")
        self.assertEqual([item["id"] for item in body["items"]], [task["id"]])

        status, body = self.request_on(
            self.app, "POST", "/api/v1/tasks", token=self.user_token, payload={"title": "无权限"},
        )
        self.assertEqual(status, 403)

        status, claimed = self.claim_task(task["id"])
        self.assertEqual(status, 200)
        self.assertEqual(claimed["status"], "CLAIMED")
        self.assertEqual(claimed["claimed_by"], self.user_id)
        self.assertIsNotNone(claimed["claimed_at"])

        status, body = self.request_on(self.app, "GET", "/api/v1/tasks")
        self.assertEqual(body["items"], [])

        status, body = self.claim_task(task["id"], token=self.other_token)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "task_already_claimed")

    def test_a_claimer_completes_a_task_with_a_note(self):
        task = self.create_task()[1]
        self.assertEqual(self.claim_task(task["id"])[0], 200)

        status, done = self.complete_task(task["id"], note="猫粮已入库")
        self.assertEqual(status, 200)
        self.assertEqual(done["status"], "COMPLETED")
        self.assertEqual(done["completion_note"], "猫粮已入库")
        self.assertIsNotNone(done["completed_at"])
        self.assertEqual(done["claimed_by"], self.user_id)

        with self.app.state.session_factory() as db:
            row = db.get(Task, task["id"])
            self.assertEqual(row.status, "COMPLETED")
            self.assertEqual(row.completion_note, "猫粮已入库")
            self.assertIsNotNone(row.completed_at)

    def test_an_admin_can_complete_a_task_claimed_by_a_volunteer(self):
        task = self.create_task()[1]
        self.assertEqual(self.claim_task(task["id"])[0], 200)
        status, done = self.complete_task(task["id"], token=self.admin_token, note="管理员代为结单")
        self.assertEqual(status, 200)
        self.assertEqual(done["status"], "COMPLETED")
        self.assertEqual(done["completion_note"], "管理员代为结单")

    def test_complete_requires_the_claimer_and_a_claimed_status(self):
        open_task = self.create_task()[1]
        status, body = self.complete_task(open_task["id"])
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "task_not_yours")

        claimed = self.create_task(title="已认领任务")[1]
        self.assertEqual(self.claim_task(claimed["id"])[0], 200)
        status, body = self.complete_task(claimed["id"], token=self.other_token)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "task_not_yours")

        status, body = self.complete_task(claimed["id"], token=self.admin_token, note="管理员关闭")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "COMPLETED")

        admin_open = self.create_task(title="管理员未认领")[1]
        status, body = self.complete_task(admin_open["id"], token=self.admin_token)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "task_not_claimed")

        cancelled = self.create_task(title="被取消任务")[1]
        self.assertEqual(self.claim_task(cancelled["id"])[0], 200)
        self.assertEqual(self.cancel_task(cancelled["id"], reason="重复发布")[0], 200)
        status, body = self.complete_task(cancelled["id"])
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "task_not_claimed")

    def test_admin_cancels_a_task_and_cannot_cancel_a_completed_one(self):
        task = self.create_task()[1]
        status, body = self.cancel_task(task["id"], reason="重复发布")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "CANCELLED")
        self.assertEqual(body["cancel_reason"], "重复发布")
        self.assertIsNotNone(body["cancelled_at"])

        status, body = self.request_on(
            self.app, "POST", "/api/v1/tasks/%s/cancel" % task["id"],
            token=self.user_token, payload={"reason": "用户取消"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "forbidden")

        done = self.create_task(title="已完成任务")[1]
        self.assertEqual(self.claim_task(done["id"])[0], 200)
        self.assertEqual(self.complete_task(done["id"], note="完成")[0], 200)
        status, body = self.cancel_task(done["id"], reason="太晚了")
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "task_already_closed")

    def test_admin_reassigns_a_task_and_releases_it_back_to_the_pool(self):
        task = self.create_task()[1]
        self.assertEqual(self.claim_task(task["id"])[0], 200)

        status, body = self.reassign_task(task["id"], target_user_id=self.other_id)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "CLAIMED")
        self.assertEqual(body["claimed_by"], self.other_id)

        status, body = self.reassign_task(task["id"], target_user_id=None)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "OPEN")
        self.assertIsNone(body["claimed_by"])
        self.assertIsNone(body["claimed_at"])

    def test_a_volunteer_can_only_release_their_own_task(self):
        task = self.create_task()[1]
        self.assertEqual(self.claim_task(task["id"])[0], 200)

        status, body = self.reassign_task(task["id"], token=self.other_token, target_user_id=None)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "forbidden")

        status, body = self.reassign_task(task["id"], token=self.user_token, target_user_id=self.other_id)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "forbidden")

        status, body = self.reassign_task(task["id"], token=self.user_token, target_user_id=None)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "OPEN")
        self.assertIsNone(body["claimed_by"])

    def test_mine_and_admin_task_lists_cover_every_status(self):
        claimed = self.create_task(title="已认领")[1]
        self.assertEqual(self.claim_task(claimed["id"])[0], 200)
        done = self.create_task(title="已完成")[1]
        self.assertEqual(self.claim_task(done["id"])[0], 200)
        self.assertEqual(self.complete_task(done["id"], note="完成")[0], 200)
        foreign = self.create_task(title="别人的")[1]
        self.assertEqual(self.claim_task(foreign["id"], token=self.other_token)[0], 200)

        status, body = self.request_on(self.app, "GET", "/api/v1/tasks/mine", token=self.user_token)
        self.assertEqual(status, 200)
        self.assertEqual({item["id"] for item in body["items"]}, {claimed["id"], done["id"]})

        status, body = self.request_on(self.app, "GET", "/api/v1/tasks/mine?status=COMPLETED", token=self.user_token)
        self.assertEqual([item["id"] for item in body["items"]], [done["id"]])

        status, body = self.request_on(self.app, "GET", "/api/v1/tasks/mine")
        self.assertEqual(status, 401)

        status, body = self.request_on(self.app, "GET", "/api/v1/admin/tasks", token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(
            {item["id"] for item in body["items"]}, {claimed["id"], done["id"], foreign["id"]},
        )

        status, body = self.request_on(self.app, "GET", "/api/v1/admin/tasks?status=COMPLETED", token=self.admin_token)
        self.assertEqual([item["id"] for item in body["items"]], [done["id"]])

        status, body = self.request_on(self.app, "GET", "/api/v1/admin/tasks", token=self.user_token)
        self.assertEqual(status, 403)

    def test_closure_actions_are_written_to_the_audit_log(self):
        point = self.create_point()[1]

        completed = self.create_task(title="审计完成")[1]
        self.assertEqual(self.claim_task(completed["id"])[0], 200)
        self.assertEqual(self.complete_task(completed["id"], note="完成")[0], 200)

        cancelled = self.create_task(title="审计取消")[1]
        self.assertEqual(self.cancel_task(cancelled["id"], reason="重复发布")[0], 200)

        reassigned = self.create_task(title="审计转派")[1]
        self.assertEqual(self.claim_task(reassigned["id"])[0], 200)
        self.assertEqual(self.reassign_task(reassigned["id"], target_user_id=None)[0], 200)

        with self.app.state.session_factory() as db:
            logs = db.scalars(select(AuditLog)).all()
        self.assertTrue(any(
            log.action == "CREATE" and log.entity_type == "feeding_point" and log.entity_id == point["id"]
            for log in logs
        ))
        self.assertTrue(any(
            log.action == "COMPLETE" and log.entity_type == "task" and log.entity_id == completed["id"]
            for log in logs
        ))
        self.assertTrue(any(
            log.action == "CANCEL" and log.entity_type == "task" and log.entity_id == cancelled["id"]
            for log in logs
        ))
        self.assertTrue(any(
            log.action == "REASSIGN" and log.entity_type == "task" and log.entity_id == reassigned["id"]
            for log in logs
        ))

    # ---- 猫咪时间线 ----------------------------------------------------

    def test_admin_creates_cat_events_and_the_public_timeline_is_ordered(self):
        cat_id = self.seed_cat()
        later = datetime(2025, 7, 1, 12, 0, tzinfo=timezone.utc).isoformat()
        earlier = datetime(2025, 6, 2, 9, 30, tzinfo=timezone.utc).isoformat()

        status, body = self.create_cat_event(cat_id, kind="NOTE", title="近况", detail="状态良好", occurred_at=later)
        self.assertEqual(status, 201)
        self.assertEqual(body["cat_id"], cat_id)
        self.assertEqual(body["kind"], "NOTE")
        self.assertEqual(body["title"], "近况")
        self.assertEqual(body["detail"], "状态良好")
        self.assertIsNotNone(body["occurred_at"])

        status, body = self.create_cat_event(cat_id, kind="RESCUE", title="相遇", occurred_at=earlier)
        self.assertEqual(status, 201)

        status, body = self.request_on(self.app, "GET", "/api/v1/cats/%s/events" % cat_id)
        self.assertEqual(status, 200)
        self.assertEqual([item["title"] for item in body["items"]], ["相遇", "近况"])
        self.assertEqual([item["kind"] for item in body["items"]], ["RESCUE", "NOTE"])

        status, _ = self.create_cat_event(cat_id, kind="UNKNOWN", title="未知")
        self.assertEqual(status, 422)

        status, body = self.create_cat_event(cat_id, token=self.user_token, title="无权限")
        self.assertEqual(status, 403)

        status, body = self.create_cat_event("missing-cat", title="不存在的猫")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "cat_not_found")

    def test_the_public_timeline_hides_cats_outside_an_active_community(self):
        self.seed_cat(cat_id="cat-pending", code="HC-PENDING", review_status="PENDING_REVIEW")
        self.seed_cat(cat_id="cat-hidden", code="HC-HIDDEN", visibility_status="HIDDEN")
        self.seed_cat(
            cat_id="cat-quiet", code="HC-QUIET", community_id="community-quiet",
            community_name="待审小区", community_status="PENDING_REVIEW",
        )

        for cat_id in ("cat-pending", "cat-hidden", "cat-quiet", "cat-missing"):
            status, body = self.request_on(self.app, "GET", "/api/v1/cats/%s/events" % cat_id)
            self.assertEqual(status, 404)
            self.assertEqual(body["code"], "cat_not_found")


if __name__ == "__main__":
    unittest.main()
