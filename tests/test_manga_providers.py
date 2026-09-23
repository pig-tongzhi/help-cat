import unittest

from sop.manga_models import RunStatus
from sop.manga_providers import (
    FakeRenderProvider,
    FakeVideoProvider,
    ProviderError,
)


class MangaProviderTest(unittest.TestCase):
    def test_duplicate_video_requests_return_same_job(self):
        provider = FakeVideoProvider()
        first = provider.generate({"shot_id": "shot-1", "prompt": "开门"}, "same-key")
        second = provider.generate({"shot_id": "shot-1", "prompt": "开门"}, "same-key")
        self.assertEqual(first.provider_job_id, second.provider_job_id)
        self.assertEqual(first.status, RunStatus.SUCCEEDED)
        self.assertEqual(provider.active_job_count, 0)

    def test_timeout_and_rate_limit_are_structured_failures(self):
        for failure_mode, error_code in (("timeout", "PROVIDER_TIMEOUT"), ("rate_limit", "PROVIDER_RATE_LIMIT")):
            provider = FakeVideoProvider(failure_mode=failure_mode)
            result = provider.generate({"shot_id": "shot-1"}, failure_mode)
            self.assertEqual(result.status, RunStatus.FAILED)
            self.assertEqual(result.error_code, error_code)

    def test_cancel_marks_running_job_cancelled(self):
        provider = FakeVideoProvider(auto_complete=False)
        result = provider.generate({"shot_id": "shot-1"}, "cancel-key")
        cancelled = provider.cancel(result.provider_job_id)
        self.assertEqual(cancelled.status, RunStatus.CANCELLED)

    def test_render_provider_requires_timeline_metadata(self):
        provider = FakeRenderProvider()
        result = provider.generate({"timeline_id": "timeline-1", "duration_ms": 1000}, "render-key")
        self.assertEqual(result.status, RunStatus.SUCCEEDED)
        with self.assertRaises(ProviderError):
            provider.generate({"timeline_id": "timeline-2", "duration_ms": -1}, "bad-render")


if __name__ == "__main__":
    unittest.main()
