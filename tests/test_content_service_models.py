import json
import unittest

from sop.content_service_models import (
    ContentItem,
    ContentPackage,
    ContentRequest,
    ContentValidationError,
    PackageStatus,
    Shot,
)
from sop.content_service_validation import validate_package, validate_request


def valid_input():
    return {
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


class ContentServiceModelTest(unittest.TestCase):
    def test_valid_request_parses_and_serializes_canonically(self):
        request = ContentRequest.from_mapping(valid_input())
        encoded = request.to_json()
        self.assertEqual(json.loads(encoded)["industry"], "本地咖啡店")
        self.assertNotIn("customer@example.test", request.public_dict().__repr__())

    def test_blank_offer_is_rejected_with_stable_code(self):
        values = valid_input()
        values["offer"] = "  "
        with self.assertRaises(ContentValidationError) as ctx:
            ContentRequest.from_mapping(values)
        self.assertEqual(ctx.exception.code, "REQUEST_INVALID")

    def test_missing_contact_is_rejected(self):
        values = valid_input()
        values.pop("contact")
        with self.assertRaises(ContentValidationError) as ctx:
            ContentRequest.from_mapping(values)
        self.assertEqual(ctx.exception.code, "CONTACT_MISSING")

    def test_missing_source_evidence_is_rejected(self):
        values = valid_input()
        values["source_evidence"] = []
        with self.assertRaises(ContentValidationError) as ctx:
            ContentRequest.from_mapping(values)
        self.assertEqual(ctx.exception.code, "SOURCE_EVIDENCE_MISSING")

    def test_package_requires_exactly_three_complete_items(self):
        item = ContentItem(
            item_id="item-1", title="标题", hook="钩子", spoken_script="口播",
            shots=(Shot(1, 3, "咖啡店", "冲咖啡", "近景", "环境声"),),
            visual_prompts=("咖啡店近景",), call_to_action="来店咨询",
            publish_copy="今天来喝咖啡", estimated_seconds=10,
        )
        package = ContentPackage("package-1", "request-1", 1, PackageStatus.NEEDS_REVIEW, (item,))
        report = validate_package(package)
        self.assertIn("CONTENT_COUNT_INVALID", report.codes)

    def test_shot_order_and_minimum_fields_are_validated(self):
        item = ContentItem(
            item_id="item-1", title="标题", hook="钩子", spoken_script="口播",
            shots=(Shot(2, 3, "咖啡店", "冲咖啡", "近景", "环境声"),),
            visual_prompts=("咖啡店近景",), call_to_action="来店咨询",
            publish_copy="今天来喝咖啡", estimated_seconds=10,
        )
        report = validate_package(ContentPackage("p", "r", 1, PackageStatus.NEEDS_REVIEW, (item, item, item)))
        self.assertIn("CONTENT_INCOMPLETE", report.codes)


if __name__ == "__main__":
    unittest.main()
