import json
import asyncio
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select

from server.helpcat.app import create_app
from server.helpcat.models import AuditLog, Cat, Community, DailyCatQuota, Task, User


class CommercialApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app("sqlite://", Path(self.tmp.name), fake_admin_openids={"admin-openid"})
        self.user_token = self.login("user-openid")
        self.admin_token = self.login("admin-openid")
        status, body = self.request("POST", "/api/v1/auth/register", payload={"username": "zack", "password": "super-pass-1"})
        self.assertEqual(status, 201)
        self.super_token = body["access_token"]
        with self.app.state.session_factory() as db:
            zack = db.scalar(select(User).where(User.username == "zack"))
            zack.role = "SUPER_ADMIN"
            self.super_id = zack.id
            self.user_id = db.scalar(select(User).where(User.openid == "user-openid")).id
            db.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, method, path, token=None, payload=None, file_tuple=None, extra_headers=None):
        headers = dict(extra_headers or {})
        if token:
            headers["Authorization"] = "Bearer " + token
        if file_tuple:
            boundary = "----HelpCatBoundary"
            filename, content, content_type = file_tuple
            body = ("--" + boundary + "\r\n" + "Content-Disposition: form-data; name=\"file\"; filename=\"" + filename + "\"\r\n" + "Content-Type: " + content_type + "\r\n\r\n").encode() + content + ("\r\n--" + boundary + "--\r\n").encode()
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        else:
            body = json.dumps(payload).encode() if payload is not None else None
            if body is not None:
                headers["Content-Type"] = "application/json"
        return asyncio.run(self.asgi_request(method, path, headers, body))

    async def asgi_request(self, method, path, headers, body):
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
            "raw_path": parsed.path.encode(), "query_string": parsed.query.encode(), "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("testclient", 50000), "server": ("testserver", 80), "scheme": "http",
        }
        await self.app(scope, receive, send)
        status = next(item["status"] for item in messages if item["type"] == "http.response.start")
        content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return status, json.loads(content.decode())

    def login(self, openid):
        status, body = self.request("POST", "/api/v1/auth/wechat-login", payload={"code": "fake:" + openid})
        self.assertEqual(status, 200)
        return body["access_token"]

    def test_health_and_wechat_login_return_production_api_shape(self):
        status, body = self.request("GET", "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_password_registration_and_login_create_user_session(self):
        status, body = self.request("POST", "/api/v1/auth/register", payload={"username": "猫咪志愿者", "password": "strong-pass-1"})
        self.assertEqual(status, 201)
        self.assertEqual(body["user"]["role"], "USER")
        status, login = self.request("POST", "/api/v1/auth/login", payload={"username": "猫咪志愿者", "password": "strong-pass-1"})
        self.assertEqual(status, 200)
        self.assertTrue(login["access_token"])
        status, _ = self.request("POST", "/api/v1/auth/login", payload={"username": "猫咪志愿者", "password": "wrong-pass"})
        self.assertEqual(status, 401)
        status, _ = self.request("POST", "/api/v1/auth/logout", login["access_token"])
        self.assertEqual(status, 200)
        status, _ = self.request("POST", "/api/v1/communities", login["access_token"], {"name": "退出后禁止操作", "street": "银湖街道"})
        self.assertEqual(status, 401)

    def test_authenticated_user_can_restore_session(self):
        status, body = self.request("GET", "/api/v1/auth/me", self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(body["role"], "ADMIN")
        self.assertTrue(body["id"])

    def test_super_admin_can_list_users_without_sensitive_fields(self):
        status, body = self.request("GET", "/api/v1/admin/users", self.super_token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(body["items"]), 3)
        zack = next(item for item in body["items"] if item["username"] == "zack")
        self.assertEqual(zack["role"], "SUPER_ADMIN")
        for sensitive in ("password_hash", "openid", "access_token", "token"):
            self.assertNotIn(sensitive, zack)

    def test_users_tasks_and_personal_submissions_are_cursor_paginated(self):
        for index in range(3):
            self.login("paged-user-%d" % index)
        status, first_users = self.request("GET", "/api/v1/admin/users?limit=2", self.super_token)
        self.assertEqual((status, len(first_users["items"])), (200, 2))
        self.assertTrue(first_users["next_cursor"])
        status, second_users = self.request(
            "GET", "/api/v1/admin/users?limit=2&cursor=" + first_users["next_cursor"], self.super_token,
        )
        self.assertEqual(status, 200)
        self.assertFalse({item["id"] for item in first_users["items"]} & {item["id"] for item in second_users["items"]})

        with self.app.state.session_factory() as db:
            for index in range(3):
                db.add(Task(title="分页任务%d" % index, description="", created_by=self.super_id))
            db.commit()
        status, first_tasks = self.request("GET", "/api/v1/tasks?limit=2")
        self.assertEqual((status, len(first_tasks["items"])), (200, 2))
        self.assertTrue(first_tasks["next_cursor"])

        _, community = self.request("POST", "/api/v1/communities", self.admin_token, {
            "name": "个人提交分页小区", "street": "银湖街道",
        })
        for index in range(2):
            self.request("POST", "/api/v1/cats", self.user_token, {
                "community_id": community["id"], "nickname": "个人猫%d" % index, "location_note": "东门",
            }, extra_headers={"Idempotency-Key": "personal-cat-%d" % index})
        status, submissions = self.request("GET", "/api/v1/me/submissions?limit=1", self.user_token)
        self.assertEqual((status, len(submissions["cats"])), (200, 1))
        self.assertTrue(submissions["next_cursor"]["cats"])

    def test_super_admin_can_promote_and_demote_user_with_audit(self):
        status, body = self.request("POST", "/api/v1/admin/users/%s/role" % self.user_id, self.super_token, {"role": "ADMIN"})
        self.assertEqual((status, body["role"]), (200, "ADMIN"))
        status, body = self.request("POST", "/api/v1/admin/users/%s/role" % self.user_id, self.super_token, {"role": "ADMIN"})
        self.assertEqual((status, body["role"]), (200, "ADMIN"))
        status, body = self.request("POST", "/api/v1/admin/users/%s/role" % self.user_id, self.super_token, {"role": "USER"})
        self.assertEqual((status, body["role"]), (200, "USER"))
        with self.app.state.session_factory() as db:
            logs = db.scalars(select(AuditLog).where(AuditLog.action == "ROLE_CHANGE", AuditLog.entity_id == self.user_id)).all()
            self.assertEqual(len(logs), 2)

    def test_only_super_admin_can_manage_roles_and_super_admin_is_immutable(self):
        status, body = self.request("GET", "/api/v1/admin/users", self.admin_token)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "super_admin_required")
        status, _ = self.request("POST", "/api/v1/admin/users/%s/role" % self.user_id, self.admin_token, {"role": "ADMIN"})
        self.assertEqual(status, 403)
        status, body = self.request("POST", "/api/v1/admin/users/%s/role" % self.super_id, self.super_token, {"role": "ADMIN"})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "super_admin_immutable")
        status, _ = self.request("POST", "/api/v1/admin/users/missing/role", self.super_token, {"role": "ADMIN"})
        self.assertEqual(status, 404)
        status, _ = self.request("POST", "/api/v1/admin/users/%s/role" % self.user_id, self.super_token, {"role": "SUPER_ADMIN"})
        self.assertEqual(status, 422)

    def test_super_admin_keeps_content_governance_permissions(self):
        status, community = self.request("POST", "/api/v1/communities", self.super_token, {"name": "超级管理员小区", "street": "银湖街道"})
        self.assertEqual(status, 201)
        self.assertEqual(community["status"], "ACTIVE")

    def test_live_community_names_are_normalized_and_database_unique(self):
        status, first = self.request("POST", "/api/v1/communities", self.user_token, {
            "name": " 星河　家园！ ", "street": "银湖街道",
        })
        self.assertEqual(status, 201)
        status, body = self.request("POST", "/api/v1/communities", self.admin_token, {
            "name": "星河家园", "street": "银湖街道",
        })
        self.assertEqual((status, body["code"]), (409, "community_exists"))
        status, _ = self.request("POST", f"/api/v1/communities/{first['id']}/review", self.admin_token, {
            "action": "reject", "note": "重复候选", "version": first["version"],
        })
        self.assertEqual(status, 200)
        status, replacement = self.request("POST", "/api/v1/communities", self.admin_token, {
            "name": "星河家园", "street": "银湖街道",
        })
        self.assertEqual((status, replacement["status"]), (201, "ACTIVE"))

    def test_admin_cat_creation_is_approved_immediately(self):
        _, community = self.request("POST", "/api/v1/communities", self.admin_token, {"name": "管理员审核小区", "street": "银湖街道"})
        status, cat = self.request("POST", "/api/v1/cats", self.admin_token, {"community_id": community["id"], "nickname": "管理员猫", "location_note": "东门"})
        self.assertEqual(status, 201)
        self.assertEqual(cat["review_status"], "APPROVED")
        self.assertEqual(len(self.request("GET", "/api/v1/cats")[1]["items"]), 1)

    def test_user_can_suggest_community_but_admin_only_can_approve(self):
        status, body = self.request("POST", "/api/v1/communities", self.user_token, {"name": "聚源福小区", "street": "银湖街道"})
        self.assertEqual(status, 201)
        community_id = body["id"]
        self.assertEqual(body["status"], "PENDING_REVIEW")
        status, _ = self.request("POST", "/api/v1/communities/%s/review" % community_id, self.user_token, {"approved": True})
        self.assertEqual(status, 403)
        status, body = self.request("POST", "/api/v1/communities/%s/review" % community_id, self.admin_token, {"approved": True})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ACTIVE")

    def test_user_cat_is_pending_and_fourth_cat_is_rejected(self):
        _, community = self.request("POST", "/api/v1/communities", self.admin_token, {"name": "银湖商业小区", "street": "银湖街道"})
        for index in range(3):
            status, body = self.request("POST", "/api/v1/cats", self.user_token, {"community_id": community["id"], "nickname": "猫%d" % index, "location_note": "东门"})
            self.assertEqual(status, 201)
            self.assertEqual(body["review_status"], "PENDING_REVIEW")
        status, body = self.request("POST", "/api/v1/cats", self.user_token, {"community_id": community["id"], "nickname": "猫3", "location_note": "东门"})
        self.assertEqual(status, 429)
        self.assertEqual(body["code"], "daily_cat_limit_reached")

    def test_user_creates_cat_with_pending_community_atomically(self):
        payload = {
            "community_candidate": {"name": "新湖家园", "street": "银湖街道", "note": "北门"},
            "nickname": "团团",
            "location_note": "北门绿化带",
        }
        status, cat = self.request("POST", "/api/v1/cats", self.user_token, payload)
        self.assertEqual(status, 201)
        self.assertEqual(cat["community_status"], "PENDING_REVIEW")
        self.assertEqual(cat["community_review_blocker"], "COMMUNITY_PENDING_REVIEW")
        with self.app.state.session_factory() as db:
            communities = db.scalars(select(Community).where(Community.name == "新湖家园")).all()
            cats = db.scalars(select(Cat).where(Cat.nickname == "团团")).all()
            logs = db.scalars(select(AuditLog).where(AuditLog.entity_id.in_([cat["community_id"], cat["id"]]))).all()
            self.assertEqual(len(communities), 1)
            self.assertEqual(len(cats), 1)
            self.assertEqual(communities[0].id, cats[0].community_id)
            self.assertEqual(len(logs), 2)

    def test_cat_creation_idempotency_returns_original_without_consuming_quota_twice(self):
        payload = {
            "community_candidate": {"name": "幂等花园", "street": "银湖街道"},
            "nickname": "幂幂",
            "location_note": "南门",
        }
        headers = {"Idempotency-Key": "cat-create-20260802-0001"}
        first_status, first = self.request("POST", "/api/v1/cats", self.user_token, payload, extra_headers=headers)
        second_status, second = self.request("POST", "/api/v1/cats", self.user_token, payload, extra_headers=headers)
        self.assertEqual((first_status, second_status), (201, 201))
        self.assertEqual(first["id"], second["id"])
        with self.app.state.session_factory() as db:
            self.assertEqual(len(db.scalars(select(Cat).where(Cat.nickname == "幂幂")).all()), 1)
            self.assertEqual(len(db.scalars(select(Community).where(Community.name == "幂等花园")).all()), 1)
            quota = db.scalar(select(DailyCatQuota).where(DailyCatQuota.user_id == self.user_id))
            self.assertEqual(quota.used_count, 1)

    def test_cat_requires_exactly_one_community_source(self):
        base = {"nickname": "团团", "location_note": "北门绿化带"}
        status, _ = self.request("POST", "/api/v1/cats", self.user_token, base)
        self.assertEqual(status, 422)
        _, community = self.request("POST", "/api/v1/communities", self.admin_token, {"name": "已审核小区", "street": "银湖街道"})
        status, _ = self.request(
            "POST",
            "/api/v1/cats",
            self.user_token,
            dict(base, community_id=community["id"], community_candidate={"name": "候选小区", "street": "银湖街道"}),
        )
        self.assertEqual(status, 422)

    def test_failed_photo_validation_rolls_back_inline_candidate(self):
        payload = {
            "community_candidate": {"name": "不应残留的小区", "street": "银湖街道"},
            "nickname": "团团",
            "location_note": "北门绿化带",
            "photo_asset_id": "not-owned",
        }
        status, body = self.request("POST", "/api/v1/cats", self.user_token, payload)
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "photo_asset_forbidden")
        with self.app.state.session_factory() as db:
            self.assertIsNone(db.scalar(select(Community).where(Community.name == "不应残留的小区")))
            self.assertIsNone(db.scalar(select(Cat).where(Cat.nickname == "团团")))

    def test_candidate_owner_edit_uses_version_and_resubmits_changes(self):
        _, cat = self.request("POST", "/api/v1/cats", self.user_token, {
            "community_candidate": {"name": "待纠正小区", "street": "银湖街道"},
            "nickname": "点点", "location_note": "东门",
        })
        community_id = cat["community_id"]
        other_token = self.login("other-user-openid")
        status, _ = self.request("PATCH", f"/api/v1/communities/{community_id}", other_token, {
            "name": "别人的修改", "street": "银湖街道", "note": "", "version": 1,
        })
        self.assertEqual(status, 403)
        status, changed = self.request("PATCH", f"/api/v1/communities/{community_id}", self.user_token, {
            "name": "待纠正家园", "street": "银湖街道", "note": "补充东门照片", "version": 1,
        })
        self.assertEqual(status, 200)
        self.assertEqual((changed["name"], changed["version"], changed["status"]), ("待纠正家园", 2, "PENDING_REVIEW"))
        status, body = self.request("PATCH", f"/api/v1/communities/{community_id}", self.user_token, {
            "name": "过期写入", "street": "银湖街道", "note": "", "version": 1,
        })
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "stale_community_version")

    def test_candidate_review_actions_require_notes_and_admin_permissions(self):
        _, candidate = self.request("POST", "/api/v1/communities", self.user_token, {"name": "联审小区", "street": "银湖街道"})
        candidate_id = candidate["id"]
        status, _ = self.request("POST", f"/api/v1/communities/{candidate_id}/review", self.user_token, {
            "action": "approve", "version": 1,
        })
        self.assertEqual(status, 403)
        status, body = self.request("POST", f"/api/v1/communities/{candidate_id}/review", self.admin_token, {
            "action": "request_changes", "note": "", "version": 1,
        })
        self.assertEqual(status, 422)
        self.assertEqual(body["code"], "review_note_required")
        status, changed = self.request("POST", f"/api/v1/communities/{candidate_id}/review", self.admin_token, {
            "action": "request_changes", "note": "请补充街道", "version": 1,
        })
        self.assertEqual((status, changed["status"], changed["version"]), (200, "NEEDS_CHANGES", 2))
        status, approved = self.request("POST", f"/api/v1/communities/{candidate_id}/review", self.super_token, {
            "action": "approve", "version": 2,
        })
        self.assertEqual((status, approved["status"]), (200, "ACTIVE"))

        _, rejected = self.request("POST", "/api/v1/communities", self.user_token, {"name": "广告小区", "street": "银湖街道"})
        status, _ = self.request("POST", f"/api/v1/communities/{rejected['id']}/review", self.super_token, {
            "action": "reject", "note": "", "version": 1,
        })
        self.assertEqual(status, 422)
        status, rejected_body = self.request("POST", f"/api/v1/communities/{rejected['id']}/review", self.super_token, {
            "action": "reject", "note": "垃圾广告", "version": 1,
        })
        self.assertEqual((status, rejected_body["status"]), (200, "REJECTED"))

    def test_explicit_community_mutations_require_current_version(self):
        _, candidate = self.request("POST", "/api/v1/communities", self.user_token, {
            "name": "版本花园", "street": "银湖街道",
        })
        status, _ = self.request("PATCH", f"/api/v1/communities/{candidate['id']}", self.user_token, {
            "name": "版本花园二期", "street": "银湖街道", "note": "",
        })
        self.assertEqual(status, 422)
        status, _ = self.request("POST", f"/api/v1/communities/{candidate['id']}/review", self.admin_token, {
            "action": "approve",
        })
        self.assertEqual(status, 422)

        _, active = self.request("POST", "/api/v1/communities", self.admin_token, {
            "name": "归档版本小区", "street": "银湖街道",
        })
        status, _ = self.request("POST", f"/api/v1/communities/{active['id']}/archive", self.admin_token, {})
        self.assertEqual(status, 422)
        status, archived = self.request("POST", f"/api/v1/communities/{active['id']}/archive", self.admin_token, {"version": 1})
        self.assertEqual((status, archived["status"], archived["version"]), (200, "ARCHIVED", 2))

    def test_admin_can_reassign_cat_after_candidate_rejection_then_approve_it(self):
        _, target = self.request("POST", "/api/v1/communities", self.admin_token, {
            "name": "正式安置小区", "street": "银湖街道",
        })
        _, cat = self.request("POST", "/api/v1/cats", self.user_token, {
            "community_candidate": {"name": "错误小区名", "street": "银湖街道"},
            "nickname": "待安置猫", "location_note": "北门",
        }, extra_headers={"Idempotency-Key": "reassign-cat-0001"})
        status, rejected = self.request("POST", f"/api/v1/communities/{cat['community_id']}/review", self.admin_token, {
            "action": "reject", "note": "地点名称无效", "version": 1,
        })
        self.assertEqual((status, rejected["status"]), (200, "REJECTED"))
        status, moved = self.request("POST", f"/api/v1/cats/{cat['id']}/community", self.admin_token, {
            "community_id": target["id"], "version": cat["version"],
        })
        self.assertEqual((status, moved["community_id"], moved["community_name"]), (200, target["id"], "正式安置小区"))
        self.assertEqual(moved["version"], cat["version"] + 1)
        status, approved = self.request("POST", f"/api/v1/cats/{cat['id']}/review", self.admin_token, {"approved": True})
        self.assertEqual((status, approved["review_status"]), (200, "APPROVED"))

    def test_legacy_community_rejection_keeps_hidden_state_during_rolling_deploy(self):
        _, candidate = self.request("POST", "/api/v1/communities", self.user_token, {
            "name": "旧客户端候选", "street": "银湖街道",
        })
        status, hidden = self.request(
            "POST", f"/api/v1/communities/{candidate['id']}/review", self.admin_token, {"approved": False},
        )
        self.assertEqual((status, hidden["status"]), (200, "HIDDEN"))

    def test_merge_reassigns_linked_cats_and_publication_waits_for_active_community(self):
        _, target = self.request("POST", "/api/v1/communities", self.admin_token, {"name": "正式小区", "street": "银湖街道"})
        _, cat = self.request("POST", "/api/v1/cats", self.user_token, {
            "community_candidate": {"name": "正式小区北区", "street": "银湖街道"},
            "nickname": "联审猫", "location_note": "北门",
        })
        status, blocked = self.request("POST", f"/api/v1/cats/{cat['id']}/review", self.admin_token, {"approved": True})
        self.assertEqual(status, 409)
        self.assertEqual(blocked["code"], "community_not_active")
        status, merged = self.request("POST", f"/api/v1/communities/{cat['community_id']}/merge", self.super_token, {
            "target_community_id": target["id"], "version": 1,
        })
        self.assertEqual((status, merged["status"], merged["merged_into_id"]), (200, "MERGED", target["id"]))
        with self.app.state.session_factory() as db:
            self.assertEqual(db.get(Cat, cat["id"]).community_id, target["id"])
        status, approved = self.request("POST", f"/api/v1/cats/{cat['id']}/review", self.admin_token, {"approved": True})
        self.assertEqual((status, approved["review_status"], approved["community_status"]), (200, "APPROVED", "ACTIVE"))

    def test_admin_community_page_includes_server_derived_bounded_linked_cat_preview(self):
        _, candidate = self.request("POST", "/api/v1/communities", self.user_token, {
            "name": "联审预览小区", "street": "银湖街道",
        })
        with self.app.state.session_factory() as db:
            for index in range(5):
                db.add(Cat(
                    community_id=candidate["id"], code="HC-PREVIEW-%d" % index,
                    nickname="预览猫%d" % index, location_note="北门", created_by=self.user_id,
                ))
            db.commit()
        status, body = self.request("GET", "/api/v1/admin/communities?limit=1", self.admin_token)
        self.assertEqual(status, 200)
        item = body["items"][0]
        self.assertEqual(item["linked_cat_count"], 5)
        self.assertEqual(len(item["linked_cats"]), 3)
        self.assertTrue(all({"id", "nickname", "code"}.issubset(preview) for preview in item["linked_cats"]))

    def test_collection_cursor_pagination_is_bounded_and_stable(self):
        for index in range(30):
            status, _ = self.request("POST", "/api/v1/communities", self.admin_token, {
                "name": f"分页小区{index:02d}", "street": "银湖街道",
            })
            self.assertEqual(status, 201)
        status, first = self.request("GET", "/api/v1/communities?limit=10")
        self.assertEqual(status, 200)
        self.assertEqual(len(first["items"]), 10)
        self.assertTrue(first["next_cursor"])
        status, second = self.request("GET", "/api/v1/communities?limit=10&cursor=" + first["next_cursor"])
        self.assertEqual(status, 200)
        self.assertEqual(len(second["items"]), 10)
        self.assertTrue(set(item["id"] for item in first["items"]).isdisjoint(item["id"] for item in second["items"]))
        status, _ = self.request("GET", "/api/v1/communities?limit=101")
        self.assertEqual(status, 422)
        status, body = self.request("GET", "/api/v1/communities?cursor=%25%25%25")
        self.assertEqual(status, 422)
        self.assertEqual(body["code"], "invalid_cursor")

    def test_admin_can_approve_hide_and_archive_cat(self):
        _, community = self.request("POST", "/api/v1/communities", self.admin_token, {"name": "管理小区", "street": "银湖街道"})
        _, cat = self.request("POST", "/api/v1/cats", self.user_token, {"community_id": community["id"], "nickname": "小拉", "location_note": "3幢附近"})
        status, _ = self.request("POST", "/api/v1/cats/%s/review" % cat["id"], self.admin_token, {"approved": True})
        self.assertEqual(status, 200)
        status, body = self.request("POST", "/api/v1/cats/%s/visibility" % cat["id"], self.admin_token, {"visible": False})
        self.assertEqual(status, 200)
        self.assertEqual(body["visibility_status"], "HIDDEN")
        status, body = self.request("POST", "/api/v1/cats/%s/archive" % cat["id"], self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(body["visibility_status"], "ARCHIVED")
        self.assertEqual(self.request("GET", "/api/v1/cats")[1]["items"], [])
        self.assertEqual(len(self.request("GET", "/api/v1/cats", self.admin_token)[1]["items"]), 1)

    def test_revoked_admin_session_cannot_read_nonpublic_cats(self):
        _, community = self.request("POST", "/api/v1/communities", self.admin_token, {"name": "撤销会话小区", "street": "银湖街道"})
        _, pending = self.request("POST", "/api/v1/cats", self.user_token, {
            "community_id": community["id"], "nickname": "待审核猫", "location_note": "东门",
        })
        status, admin_view = self.request("GET", "/api/v1/cats", self.admin_token)
        self.assertEqual(status, 200)
        self.assertIn(pending["id"], [item["id"] for item in admin_view["items"]])
        self.assertEqual(self.request("POST", "/api/v1/auth/logout", self.admin_token)[0], 200)
        status, public_view = self.request("GET", "/api/v1/cats", self.admin_token)
        self.assertEqual(status, 200)
        self.assertNotIn(pending["id"], [item["id"] for item in public_view["items"]])

    def test_image_upload_rejects_non_image_and_accepts_small_image(self):
        status, _ = self.request("POST", "/api/v1/media/images", self.user_token, file_tuple=("note.txt", b"hello", "text/plain"))
        self.assertEqual(status, 415)
        status, _ = self.request("POST", "/api/v1/media/images", self.user_token, file_tuple=("fake.jpg", b"not-an-image", "image/jpeg"))
        self.assertEqual(status, 415)
        status, body = self.request("POST", "/api/v1/media/images", self.user_token, file_tuple=("cat.jpg", b"\xff\xd8\xff\xe0fake-jpeg", "image/jpeg"))
        self.assertEqual(status, 201)
        self.assertTrue(body["object_key"])


if __name__ == "__main__":
    unittest.main()
