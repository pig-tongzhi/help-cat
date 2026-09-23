import tempfile
import unittest
from pathlib import Path

from sop.content_service import ContentService, DeterministicContentGenerator, GenerationError
from dataclasses import replace

from sop.content_service_models import ContentItem, PackageStatus


def valid_input(request_id="request-1"):
    return {
        "request_id": request_id,
        "industry": "本地咖啡店",
        "offer": "手冲咖啡和工作日早餐",
        "audience": "附近上班族",
        "platform": "抖音",
        "goal": "到店咨询",
        "tone": "真实、轻松",
        "prohibited_items": "不夸大功效",
        "source_evidence": ["店主提供的菜单和营业时间"],
        "contact": "customer@example.test",
        "price_assumption": 99,
    }


class FailingGenerator:
    def generate(self, request, item_index):
        raise GenerationError("PROVIDER_FAILED", "offline provider failed")


class RiskyGenerator(DeterministicContentGenerator):
    def generate(self, request, item_index):
        return replace(super().generate(request, item_index), spoken_script="保证爆款，百分百成交")


class ContentServiceTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.service = ContentService(Path(self.tempdir.name), DeterministicContentGenerator())

    def tearDown(self):
        self.tempdir.cleanup()

    def test_valid_request_generates_exactly_three_review_items(self):
        request = self.service.create_request(valid_input())
        package = self.service.generate_package(request.request_id, "idem-1")
        self.assertEqual(package.status, PackageStatus.NEEDS_REVIEW)
        self.assertEqual(len(package.items), 3)
        self.assertTrue(all(len(item.shots) == 3 for item in package.items))

    def test_same_idempotency_key_returns_same_package_without_duplicate(self):
        request = self.service.create_request(valid_input())
        first = self.service.generate_package(request.request_id, "idem-same")
        second = self.service.generate_package(request.request_id, "idem-same")
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(self.service.repository.list_packages(request.request_id)), 1)

    def test_changed_request_creates_traceable_new_version(self):
        request = self.service.create_request(valid_input("request-version"))
        self.service.generate_package(request.request_id, "idem-v1")
        changed = valid_input("request-version")
        changed["offer"] = "冷萃咖啡外带"
        self.service.create_request(changed)
        second = self.service.generate_package(request.request_id, "idem-v2")
        self.assertEqual(second.version, 2)
        self.assertEqual(len(self.service.repository.list_packages(request.request_id)), 2)

    def test_generation_failure_does_not_create_exportable_package(self):
        service = ContentService(Path(self.tempdir.name), FailingGenerator())
        request = service.create_request(valid_input("request-fail"))
        with self.assertRaises(GenerationError) as ctx:
            service.generate_package(request.request_id, "idem-fail")
        self.assertEqual(ctx.exception.code, "PROVIDER_FAILED")
        self.assertEqual(service.repository.list_packages(request.request_id), [])

    def test_one_rejected_item_blocks_export_until_all_three_are_approved(self):
        request = self.service.create_request(valid_input("request-review"))
        package = self.service.generate_package(request.request_id, "idem-review")
        self.service.review_item(package.package_id, package.items[0].item_id, "reject", "需要补充事实依据")
        with self.assertRaises(Exception) as ctx:
            self.service.export_package(package.package_id)
        self.assertEqual(ctx.exception.code, "PACKAGE_NOT_APPROVED")

    def test_three_approved_items_export_and_redact_contact(self):
        request = self.service.create_request(valid_input("request-export"))
        package = self.service.generate_package(request.request_id, "idem-export")
        for item in package.items:
            self.service.review_item(package.package_id, item.item_id, "approve")
        artifact = self.service.export_package(package.package_id)
        self.assertIn("短视频内容包", artifact.content)
        self.assertNotIn("customer@example.test", artifact.content)
        self.assertEqual(self.service.repository.get_package(package.package_id).status, PackageStatus.EXPORTED)

    def test_quote_includes_scope_price_and_no_guarantee_disclaimer(self):
        request = self.service.create_request(valid_input("request-quote"))
        quote = self.service.quote_summary(request.request_id)
        self.assertEqual(len(quote.deliverables), 3)
        self.assertEqual(quote.price, 99)
        self.assertIn("不承诺", quote.disclaimer)

    def test_unsupported_outcome_claim_is_rejected_before_package_save(self):
        service = ContentService(Path(self.tempdir.name), RiskyGenerator())
        request = service.create_request(valid_input("request-risk"))
        with self.assertRaises(GenerationError) as ctx:
            service.generate_package(request.request_id, "idem-risk")
        self.assertEqual(ctx.exception.code, "CONTENT_INVALID")
        self.assertEqual(service.repository.list_packages(request.request_id), [])


if __name__ == "__main__":
    unittest.main()
