import os
import unittest
from unittest.mock import patch

from sop.manga_models import RunStatus
from sop.volcengine_provider import (
    FakeTransport,
    HttpResponse,
    ProviderConfig,
    VolcengineHmacSigner,
    VolcengineVideoProvider,
    validate_media_url,
)


class VolcengineProviderTest(unittest.TestCase):
    def full_env(self):
        return {
            "VOLCENGINE_ACCESS_KEY": "access-test",
            "VOLCENGINE_SECRET_KEY": "secret-do-not-log",
            "VOLCENGINE_ENDPOINT": "https://visual.example.test",
            "VOLCENGINE_REGION": "cn-north-1",
            "VOLCENGINE_SERVICE": "cv",
            "VOLCENGINE_REQ_KEY": "jimeng_test_v1",
        }

    def test_config_redacts_secret_and_requires_fields(self):
        with patch.dict(os.environ, self.full_env(), clear=True):
            config = ProviderConfig.from_env()
        redacted = config.redacted()
        self.assertNotIn("secret-do-not-log", repr(redacted))
        self.assertEqual(redacted["region"], "cn-north-1")

        incomplete = dict(self.full_env())
        del incomplete["VOLCENGINE_SECRET_KEY"]
        with patch.dict(os.environ, incomplete, clear=True):
            with self.assertRaises(ValueError):
                ProviderConfig.from_env()

    def test_dry_run_does_not_call_transport(self):
        transport = FakeTransport()
        config = ProviderConfig.from_mapping(self.full_env())
        provider = VolcengineVideoProvider(config, transport)
        result = provider.dry_run({"prompt": "原创雨夜旧宅"})
        self.assertTrue(result["ready"])
        self.assertEqual(transport.call_count, 0)

    def test_submit_poll_and_result_mapping(self):
        transport = FakeTransport(
            post_response=HttpResponse(200, {}, {"data": {"task_id": "task-1"}}),
            get_responses=[
                HttpResponse(200, {}, {"data": {"status": "running"}}),
                HttpResponse(200, {}, {"data": {"status": "succeeded", "video_url": "https://cdn.example.test/out.mp4"}}),
            ],
        )
        provider = VolcengineVideoProvider(ProviderConfig.from_mapping(self.full_env()), transport)
        result = provider.generate({"prompt": "原创二维漫画雨夜"}, "shot-key")
        self.assertEqual(result.status, RunStatus.SUCCEEDED)
        self.assertEqual(result.output_refs, ("https://cdn.example.test/out.mp4",))
        self.assertEqual(transport.post_calls, 1)
        self.assertEqual(transport.get_calls, 2)

    def test_duplicate_idempotency_key_does_not_submit_twice(self):
        transport = FakeTransport(
            post_response=HttpResponse(200, {}, {"data": {"task_id": "task-1"}}),
            get_responses=[HttpResponse(200, {}, {"data": {"status": "succeeded", "video_url": "https://cdn.example.test/out.mp4"}})],
        )
        provider = VolcengineVideoProvider(ProviderConfig.from_mapping(self.full_env()), transport)
        first = provider.generate({"prompt": "同一镜头"}, "same-key")
        second = provider.generate({"prompt": "同一镜头"}, "same-key")
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(transport.post_calls, 1)

    def test_missing_config_never_calls_transport(self):
        transport = FakeTransport()
        config = ProviderConfig.from_mapping({"VOLCENGINE_ENDPOINT": "https://example.test"})
        provider = VolcengineVideoProvider(config, transport)
        result = provider.generate({"prompt": "测试"}, "missing-config")
        self.assertEqual(result.error_code, "CONFIG_MISSING")
        self.assertEqual(transport.call_count, 0)

    def test_auth_and_malformed_response_are_structured_failures(self):
        auth_transport = FakeTransport(post_response=HttpResponse(401, {}, {"error": "unauthorized"}))
        provider = VolcengineVideoProvider(ProviderConfig.from_mapping(self.full_env()), auth_transport)
        auth_result = provider.generate({"prompt": "测试"}, "auth")
        self.assertEqual(auth_result.error_code, "AUTH_FAILED")

        malformed_transport = FakeTransport(post_response=HttpResponse(200, {}, "not-json"))
        provider = VolcengineVideoProvider(ProviderConfig.from_mapping(self.full_env()), malformed_transport)
        malformed_result = provider.generate({"prompt": "测试"}, "malformed")
        self.assertEqual(malformed_result.error_code, "RESPONSE_INVALID")

    def test_result_url_must_be_https_and_within_size(self):
        self.assertIsNone(validate_media_url("https://cdn.example.test/a.mp4", "video/mp4", 100, 100))
        self.assertEqual(validate_media_url("http://cdn.example.test/a.mp4", "video/mp4", 100, 100), "URL_NOT_HTTPS")
        self.assertEqual(validate_media_url("https://cdn.example.test/a.mp4", "video/mp4", 101, 100), "MEDIA_TOO_LARGE")
        self.assertEqual(validate_media_url("https://cdn.example.test/a.txt", "text/plain", 10, 100), "CONTENT_TYPE_INVALID")

    def test_production_signer_adds_required_headers_without_exposing_secret(self):
        config = ProviderConfig.from_mapping(self.full_env())
        headers = VolcengineHmacSigner().sign(
            "POST",
            config.endpoint,
            {"Action": "CVSync2AsyncSubmitTask", "Version": config.api_version},
            {"Content-Type": "application/json", "Host": "visual.example.test"},
            b'{"prompt":"test"}',
            config,
        )
        self.assertIn("Authorization", headers)
        self.assertIn("X-Date", headers)
        self.assertIn("X-Content-Sha256", headers)
        self.assertNotIn(config.secret_key, repr(headers))


if __name__ == "__main__":
    unittest.main()
