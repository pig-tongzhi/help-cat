import threading
import unittest

from sop.rescue_models import ReportStatus, TaskStatus, TnrStatus
from sop.rescue_service import RescueService, RescueServiceError


class RescueServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = RescueService()
        self.point = self.service.create_feeding_point(
            "yinhu", "银湖街道橙意小区", "银湖街道·橙意小区", actor_id="admin"
        )

    def test_report_review_creates_one_open_task(self):
        report = self.service.create_report(
            {"type": "INJURY", "area_id": "yinhu", "title": "橘猫受伤", "feeding_point_id": self.point.id},
            "request-1",
        )
        task = self.service.review_report(report.id, True, "admin")
        self.assertEqual(report.status, ReportStatus.APPROVED)
        self.assertEqual(task.status, TaskStatus.OPEN)
        self.assertEqual(len(self.service.tasks), 1)

    def test_duplicate_idempotency_key_returns_original_report(self):
        first = self.service.create_report({"type": "ABNORMAL", "area_id": "yinhu", "title": "重复上报"}, "same")
        second = self.service.create_report({"type": "ABNORMAL", "area_id": "yinhu", "title": "应被忽略"}, "same")
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.service.reports), 1)

    def test_rejected_report_has_no_task_or_audit_side_effect(self):
        report = self.service.create_report({"type": "INJURY", "area_id": "yinhu", "title": "误报"}, "reject-1")
        before_logs = len(self.service.audit_logs)
        self.service.review_report(report.id, False, "admin")
        self.assertEqual(report.status, ReportStatus.REJECTED)
        self.assertEqual(len(self.service.tasks), 0)
        self.assertEqual(len(self.service.audit_logs), before_logs + 1)

    def test_only_one_concurrent_claim_succeeds(self):
        report = self.service.create_report({"type": "INJURY", "area_id": "yinhu", "title": "并发"}, "con-1")
        task = self.service.review_report(report.id, True, "admin")
        outcomes = []

        def claim(user):
            try:
                outcomes.append(self.service.claim_task(task.id, user).assignee_id)
            except RescueServiceError:
                outcomes.append("FAILED")

        threads = [threading.Thread(target=claim, args=("volunteer-" + str(i),)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes), ["FAILED", task.assignee_id])

    def test_public_snapshot_masks_exact_coordinates(self):
        point = self.service.create_feeding_point(
            "yinhu", "精确点", "银湖街道·精确点", latitude=30.2, longitude=120.1, actor_id="admin"
        )
        public = self.service.public_snapshot()["feeding_points"]
        item = next(row for row in public if row["id"] == point.id)
        self.assertNotIn("latitude", item)
        self.assertNotIn("longitude", item)

    def test_tnr_update_requires_next_state(self):
        cat = self.service.create_cat(self.point.id, "YH-001", actor_id="admin")
        self.service.update_tnr(cat.id, TnrStatus.TO_CATCH, "admin")
        with self.assertRaises(RescueServiceError):
            self.service.update_tnr(cat.id, TnrStatus.RELEASED, "admin")

    def test_non_admin_cannot_review_or_export(self):
        report = self.service.create_report({"type": "INJURY", "area_id": "yinhu", "title": "权限"}, "role-1")
        with self.assertRaises(RescueServiceError):
            self.service.review_report(report.id, True, "visitor")
        with self.assertRaises(RescueServiceError):
            self.service.export("json", actor_id="visitor")

    def test_ordinary_user_can_create_pending_cat_and_only_owner_can_see_it(self):
        cat = self.service.create_cat(
            self.point.id,
            "YH-USER-001",
            actor_id="user-1",
            nickname="小拉",
            living_status="常住",
            location_note="聚源福小区东门附近",
        )
        self.assertEqual(cat.review_status.value, "PENDING_REVIEW")
        self.assertEqual(self.service.list_cats("user-1")[0].id, cat.id)
        self.assertEqual(self.service.list_cats("user-2"), [])
        self.assertEqual(self.service.list_cats("admin")[0].id, cat.id)

    def test_ordinary_user_is_limited_to_three_new_cats_per_day(self):
        for index in range(3):
            self.service.create_cat(self.point.id, "YH-LIMIT-%s" % index, actor_id="user-limit")
        with self.assertRaisesRegex(RescueServiceError, "daily_cat_limit_reached"):
            self.service.create_cat(self.point.id, "YH-LIMIT-3", actor_id="user-limit")

    def test_admin_approves_cat_and_it_becomes_public(self):
        cat = self.service.create_cat(self.point.id, "YH-APPROVE", actor_id="user-1")
        self.service.review_cat(cat.id, True, "admin")
        self.assertEqual(self.service.list_cats("user-2")[0].id, cat.id)
        self.assertEqual(cat.review_status.value, "APPROVED")

    def test_non_admin_cannot_create_report_but_can_claim_admin_task(self):
        with self.assertRaisesRegex(RescueServiceError, "forbidden"):
            self.service.create_report(
                {"type": "INJURY", "area_id": "yinhu", "title": "不允许"},
                "user-report-1",
                actor_id="user-1",
            )
        task = self.service.create_task("去聚源福小区投喂", "补充猫粮并拍照", "admin")
        self.assertEqual(self.service.list_tasks("user-1")[0].id, task.id)
        self.service.claim_task(task.id, "user-1")
        self.assertEqual(task.assignee_id, "user-1")

    def test_ordinary_user_can_suggest_community_and_admin_can_approve_it(self):
        community = self.service.create_community("聚源福小区", "银湖街道", "user-1")
        self.assertEqual(community.status, "PENDING_REVIEW")
        self.assertEqual(self.service.list_communities("user-1")[0].id, community.id)
        self.assertEqual(self.service.list_communities("user-2"), [])
        self.service.review_community(community.id, True, "admin")
        self.assertEqual(self.service.list_communities("user-2")[0].name, "聚源福小区")

    def test_admin_can_hide_and_archive_cat_without_physical_delete(self):
        cat = self.service.create_cat(self.point.id, "YH-GOV-001", actor_id="admin")
        self.service.set_cat_visibility(cat.id, False, "admin")
        self.assertEqual(self.service.list_cats("user-2"), [])
        self.assertEqual(self.service.admin_list_cats("admin")[0].id, cat.id)
        self.service.archive_cat(cat.id, "admin")
        self.assertEqual(len(self.service.cats), 1)
        self.assertEqual(self.service.admin_list_cats("admin")[0].status, "ARCHIVED")


if __name__ == "__main__":
    unittest.main()
