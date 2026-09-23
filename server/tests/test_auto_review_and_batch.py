"""投稿自动预检（规则 + 影子模式）与后台批量审核。

自动预检的边界必须被钉住：**任一条规则不满足就不能自动公开**，尤其是"位置描述里
出现门牌号"和"健康状态是可能需要帮助"这两条 —— 公开页面的隐私与医疗表述红线就靠
它们兜着。影子模式另有一条硬要求：**只写审计，不动任何状态**。

批量审核要保证：单条与批量走同一段实现（校验不会分叉）、带版本号防止覆盖别人的改动、
不带管理权限进不来、以及"通过猫咪时把它待审的小区一起开放"。
"""

import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from sqlalchemy import select

from server.helpcat import auto_review
from server.helpcat.app import create_app
from server.helpcat.models import AuditLog, Cat, Community


def jpeg_bytes(size=(64, 48)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (210, 190, 165)).save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


class RuleTests(unittest.TestCase):
    """纯规则，不碰 HTTP：表格驱动，方便一眼看出边界。"""

    def clean(self, **overrides):
        values = dict(
            nickname="小花", location_note="常在小区花坛边晒太阳", health_status="HEALTHY",
            has_photo=True, community_is_active=True,
        )
        values.update(overrides)
        return auto_review.cat_decision(**values)

    def test_a_clean_submission_is_approved(self):
        decision = self.clean()
        self.assertTrue(decision.approved)
        self.assertIn("has_photo", decision.passed)
        self.assertEqual((), decision.failed)

    def test_precise_addresses_never_auto_approve(self):
        for note in ("3号楼门口", "12 栋楼下", "5单元门口", "7楼阳台", "小区 2 幢前面"):
            with self.subTest(note=note):
                decision = self.clean(location_note=note)
                self.assertFalse(decision.approved)
                self.assertIn("location_not_precise", decision.failed)

    def test_general_locations_still_pass(self):
        for note in ("北门石凳旁", "绿化带一带", "便利店门口的纸箱里"):
            with self.subTest(note=note):
                self.assertTrue(self.clean(location_note=note).approved, note)

    def test_medical_and_missing_photo_stay_manual(self):
        self.assertIn("not_medical", self.clean(health_status="NEEDS_HELP").failed)
        self.assertIn("has_photo", self.clean(has_photo=False).failed)
        self.assertIn("community_active", self.clean(community_is_active=False).failed)

    def test_contact_details_and_test_markers_are_caught(self):
        self.assertIn("clean_text", self.clean(location_note="有事微信联系我").failed)
        self.assertIn("clean_text", self.clean(nickname="[QA-20260801] 橘猫").failed)
        self.assertIn("clean_text", self.clean(location_note="见 http://spam.example").failed)

    def test_community_rules_require_a_known_street(self):
        ok = auto_review.community_decision(name="银湖花园", street="银湖街道", known_streets={"银湖街道"})
        self.assertTrue(ok.approved)
        unknown = auto_review.community_decision(name="银湖花园", street="城西街道", known_streets={"银湖街道"})
        self.assertIn("street_known", unknown.failed)
        junk = auto_review.community_decision(name="[QA-20260801] 星河家园", street="银湖街道", known_streets={"银湖街道"})
        self.assertIn("clean_text", junk.failed)

    def test_describe_says_which_rules_decided(self):
        self.assertIn("满足：有照片", self.clean().describe())
        # 不通过时要写明"未满足"，否则一串正向短语读起来像通过了
        rejected = self.clean(location_note="3号楼").describe()
        self.assertIn("未自动通过", rejected)
        self.assertIn("未满足：位置描述不含门牌号", rejected)


class SubmissionWiringTests(unittest.TestCase):
    """预检接到建档流程上的行为：off / shadow / on 三种模式。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app("sqlite://", storage_root=Path(self.tmp.name), fake_admin_openids={"admin-openid"})
        self.admin = self.login("fake:admin-openid")
        self.user = self.login("fake:user-openid")
        status, community = self.request(
            "POST", "/api/v1/communities", self.admin,
            payload={"name": "银湖花园", "street": "银湖街道"},
        )
        self.assertEqual(201, status, community)
        self.community_id = community["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def mode(self, value):
        self.app.state.settings.auto_review = value

    def submit_cat(self, nickname="小花", location_note="常在花坛边晒太阳", health_status="HEALTHY",
                   with_photo=True, community_id=None, community_candidate=None):
        photo_asset_id = None
        if with_photo:
            status, asset = self.request("POST", "/api/v1/media/images", self.user,
                                         file_tuple=("photo.jpg", jpeg_bytes(), "image/jpeg"))
            self.assertEqual(201, status, asset)
            photo_asset_id = asset["id"]
        payload = {"nickname": nickname, "location_note": location_note,
                   "health_status": health_status, "photo_asset_id": photo_asset_id}
        if community_candidate:
            payload["community_candidate"] = community_candidate
        else:
            payload["community_id"] = community_id or self.community_id
        return self.request("POST", "/api/v1/cats", self.user, payload=payload)

    def audit_actions(self, entity_type=None):
        with self.app.state.session_factory() as session:
            rows = session.scalars(select(AuditLog).order_by(AuditLog.created_at)).all()
            return [(row.action, row.entity_type, row.after_json) for row in rows
                    if entity_type is None or row.entity_type == entity_type]

    def community_status(self, name):
        with self.app.state.session_factory() as session:
            community = session.scalar(select(Community).where(Community.name == name))
            return community.status if community else None

    def test_off_mode_keeps_everything_pending(self):
        self.mode(auto_review.MODE_OFF)
        status, cat = self.submit_cat()
        self.assertEqual(201, status, cat)
        self.assertEqual("PENDING_REVIEW", cat["review_status"])
        self.assertEqual([], self.audit_actions("cat") and [item for item in self.audit_actions("cat") if item[0].startswith("AUTO")])

    def test_shadow_mode_writes_the_verdict_without_changing_anything(self):
        self.mode(auto_review.MODE_SHADOW)
        status, cat = self.submit_cat(
            community_candidate={"name": "银湖新村", "street": "银湖街道", "note": ""})
        self.assertEqual(201, status, cat)
        self.assertEqual("PENDING_REVIEW", cat["review_status"], "影子模式不能改动状态")
        self.assertEqual("PENDING_REVIEW", self.community_status("银湖新村"), "影子模式不能开放小区")

        auto_rows = [row for row in self.audit_actions() if row[0].startswith("AUTO")]
        self.assertTrue(auto_rows, "影子模式必须留下审计，否则没有观察价值")
        payload = json.loads(auto_rows[-1][2])
        self.assertEqual("shadow", payload["mode"])
        self.assertFalse(payload["auto_approved"])
        self.assertTrue(payload["would_approve"], "这份投稿本身是干净的，应该被判为'会通过'")

    def test_on_mode_publishes_the_cat_and_opens_its_new_community_together(self):
        self.mode(auto_review.MODE_ON)
        status, cat = self.submit_cat(
            community_candidate={"name": "银湖新村", "street": "银湖街道", "note": ""})
        self.assertEqual(201, status, cat)
        self.assertEqual("APPROVED", cat["review_status"], "规则全过就该直接公开")
        self.assertEqual("ACTIVE", self.community_status("银湖新村"), "新小区要和猫一起开放，否则猫照样看不见")
        with self.app.state.session_factory() as session:
            actions = {row.action for row in session.scalars(select(AuditLog)).all()}
        self.assertIn("AUTO_APPROVE", actions)

    def test_on_mode_still_holds_back_risky_submissions(self):
        self.mode(auto_review.MODE_ON)
        for label, kwargs in (
            ("门牌号", {"location_note": "3号楼门口"}),
            ("医疗类", {"health_status": "NEEDS_HELP"}),
            ("没有照片", {"with_photo": False}),
        ):
            with self.subTest(label=label):
                status, cat = self.submit_cat(**kwargs)
                self.assertEqual(201, status, cat)
                self.assertEqual("PENDING_REVIEW", cat["review_status"], label)

    def test_on_mode_does_not_open_a_community_with_an_unknown_street(self):
        self.mode(auto_review.MODE_ON)
        status, cat = self.submit_cat(
            community_candidate={"name": "城西花园", "street": "城西街道", "note": ""})
        self.assertEqual(201, status, cat)
        self.assertEqual("PENDING_REVIEW", cat["review_status"])
        self.assertEqual("PENDING_REVIEW", self.community_status("城西花园"))

    def test_admins_are_unaffected_by_the_mode(self):
        self.mode(auto_review.MODE_OFF)
        status, cat = self.request(
            "POST", "/api/v1/cats", self.admin,
            payload={"nickname": "管理员建的", "location_note": "3号楼", "community_id": self.community_id},
        )
        self.assertEqual(201, status, cat)
        self.assertEqual("APPROVED", cat["review_status"])

    # ---- 脚手架 ---------------------------------------------------------

    def login(self, code):
        status, body = self.request("POST", "/api/v1/auth/wechat-login", None, payload={"code": code})
        self.assertEqual(200, status, body)
        return body["access_token"]

    def request(self, method, path, token, payload=None, file_tuple=None):
        status, _headers, content = asyncio.run(self.asgi_request(method, path, token, payload, file_tuple))
        return status, (json.loads(content.decode()) if content else {})

    async def asgi_request(self, method, path, token, payload, file_tuple):
        headers, body = {}, None
        if token:
            headers["Authorization"] = "Bearer " + token
        if file_tuple:
            boundary = "----HelpCatReviewBoundary"
            filename, content, content_type = file_tuple
            body = (
                "--" + boundary + "\r\n"
                'Content-Disposition: form-data; name="file"; filename="' + filename + '"\r\n'
                "Content-Type: " + content_type + "\r\n\r\n"
            ).encode() + content + ("\r\n--" + boundary + "--\r\n").encode()
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        elif payload is not None:
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

        await self.app({
            "type": "http", "http_version": "1.1", "method": method, "path": parsed.path,
            "raw_path": parsed.path.encode(), "query_string": parsed.query.encode(),
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
            "client": ("testclient", 50000), "server": ("testserver", 80), "scheme": "http",
        }, receive, send)
        start = next(item for item in messages if item["type"] == "http.response.start")
        content = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return start["status"], {}, content


class BatchReviewTests(SubmissionWiringTests):
    """后台批量通过：一次点击清队列，并且把待审小区一起带上。"""

    def setUp(self):
        super().setUp()
        self.mode(auto_review.MODE_OFF)   # 先全部进待审，再批量处理

    def pending_cat(self, nickname, note="花坛边"):
        status, cat = self.submit_cat(nickname=nickname, location_note=note)
        self.assertEqual(201, status, cat)
        return cat

    def test_batch_approval_approves_cats_and_opens_their_pending_community(self):
        cat_one = self.pending_cat("阿黄")
        cat_two = self.pending_cat("小白")
        # 一只挂在新小区下（待审），一只挂在已开放小区下
        status, cat_three = self.submit_cat(
            nickname="新小区的猫", community_candidate={"name": "银湖新村", "street": "银湖街道", "note": ""})
        self.assertEqual(201, status, cat_three)

        status, result = self.request(
            "POST", "/api/v1/admin/reviews/approve", self.admin,
            payload={"cats": [{"id": cat_one["id"]}, {"id": cat_two["id"]}, {"id": cat_three["id"]}]},
        )
        self.assertEqual(200, status, result)
        self.assertEqual(3, result["approved_count"], result)
        self.assertEqual(0, result["skipped_count"], result)
        self.assertTrue(result["opened_communities"], "待审小区应当被一起开放")
        self.assertEqual("ACTIVE", self.community_status("银湖新村"))

        with self.app.state.session_factory() as session:
            for cat_id in (cat_one["id"], cat_two["id"], cat_three["id"]):
                self.assertEqual("APPROVED", session.get(Cat, cat_id).review_status)

    def test_batch_reports_a_stale_version_instead_of_overwriting(self):
        cat = self.pending_cat("版本冲突")
        status, result = self.request(
            "POST", "/api/v1/admin/reviews/approve", self.admin,
            payload={"cats": [{"id": cat["id"], "version": cat["version"] + 5}]},
        )
        self.assertEqual(200, status, result)
        self.assertEqual(0, result["approved_count"])
        self.assertEqual("stale_cat_version", result["cats"][0]["code"])
        with self.app.state.session_factory() as session:
            self.assertEqual("PENDING_REVIEW", session.get(Cat, cat["id"]).review_status, "冲突时不能改状态")

    def test_batch_approves_communities_directly_too(self):
        status, community = self.request(
            "POST", "/api/v1/communities", self.user,
            payload={"name": "待审小区", "street": "银湖街道"},
        )
        self.assertEqual(201, status, community)
        status, result = self.request(
            "POST", "/api/v1/admin/reviews/approve", self.admin,
            payload={"communities": [{"id": community["id"], "version": community["version"]}]},
        )
        self.assertEqual(200, status, result)
        self.assertEqual(1, result["approved_count"], result)
        self.assertEqual("ACTIVE", self.community_status("待审小区"))

    def test_a_non_admin_cannot_batch_approve(self):
        cat = self.pending_cat("无权限")
        status, body = self.request(
            "POST", "/api/v1/admin/reviews/approve", self.user, payload={"cats": [{"id": cat["id"]}]})
        self.assertEqual(403, status, body)

    def test_an_empty_batch_is_rejected(self):
        status, body = self.request("POST", "/api/v1/admin/reviews/approve", self.admin, payload={})
        self.assertEqual(422, status, body)

    def test_pending_counts_endpoint_matches_the_queue(self):
        self.pending_cat("待审一")
        self.pending_cat("待审二")
        status, counts = self.request("GET", "/api/v1/admin/reviews/pending", self.admin)
        self.assertEqual(200, status, counts)
        self.assertEqual(2, counts["cats"])


if __name__ == "__main__":
    unittest.main()
