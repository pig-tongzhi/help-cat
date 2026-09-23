import tempfile
import unittest
from pathlib import Path

from sop.manga_pipeline import MangaPipeline, ProjectInput
from sop.manga_providers import FakeRenderProvider, FakeTextProvider, FakeVoiceProvider
from sop.manga_repository import MangaRepository
from sop.volcengine_provider import FakeTransport, HttpResponse, ProviderConfig, VolcengineVideoProvider


class VolcengineIntegrationTest(unittest.TestCase):
    def test_pipeline_can_use_offline_volcengine_provider_for_original_shot(self):
        transport = FakeTransport(
            post_response=HttpResponse(200, {}, {"data": {"task_id": "offline-task-1"}}),
            get_responses=[HttpResponse(200, {}, {"data": {"status": "succeeded", "video_url": "https://offline.example.test/test-shot.mp4"}})],
        )
        provider = VolcengineVideoProvider(
            ProviderConfig.from_mapping({
                "endpoint": "https://visual.example.test",
                "region": "cn-north-1",
                "service": "cv",
                "access_key": "offline-access",
                "secret_key": "offline-secret",
                "req_key": "offline-test",
            }),
            transport,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = MangaPipeline(
                MangaRepository(Path(temp_dir)),
                {"text": FakeTextProvider(), "video": provider, "voice": FakeVoiceProvider(), "render": FakeRenderProvider()},
            )
            pipeline.create_project(ProjectInput("s", "e", "原创测试", "原创雨夜旧宅故事。" * 3, "ORIGINAL", 90, "SINGLE", "二维漫画"))
            pipeline.run_story_and_script("s", "e")
            pipeline.run_assets("s", "e")
            pipeline.run_storyboard("s", "e")
            result = pipeline.run_shot("s", "e", "shot-1")
        self.assertTrue(result.passed)
        self.assertEqual(transport.post_calls, 1)
        self.assertEqual(transport.get_calls, 1)
        self.assertEqual(transport.requests[0]["body"]["req_key"], "offline-test")
        self.assertEqual(transport.requests[1]["query"]["task_id"], "offline-task-1")


if __name__ == "__main__":
    unittest.main()
