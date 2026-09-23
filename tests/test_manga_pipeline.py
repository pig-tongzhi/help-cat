import tempfile
import unittest
from pathlib import Path

from sop.manga_models import EpisodeMode, Stage
from sop.manga_pipeline import MangaPipeline, ProjectInput
from sop.manga_providers import FakeRenderProvider, FakeTextProvider, FakeVideoProvider, FakeVoiceProvider
from sop.manga_repository import MangaRepository


class MangaPipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = MangaRepository(Path(self.temp_dir.name))
        self.video = FakeVideoProvider()
        self.pipeline = MangaPipeline(
            self.repo,
            {
                "text": FakeTextProvider(),
                "video": self.video,
                "voice": FakeVoiceProvider(),
                "render": FakeRenderProvider(),
            },
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_project(self):
        return self.pipeline.create_project(
            ProjectInput(
                series_id="series-1",
                episode_id="episode-1",
                title="测试漫剧",
                story_brief="一个年轻人在雨夜回到旧宅，发现一封改变命运的信。" * 2,
                source_type="ORIGINAL",
                target_duration_sec=90,
                episode_mode="SINGLE",
                visual_style="二维悬疑漫画",
            )
        )

    def test_single_episode_runs_in_stage_order(self):
        self.create_project()
        self.assertTrue(self.pipeline.run_story_and_script("series-1", "episode-1").passed)
        self.assertTrue(self.pipeline.run_assets("series-1", "episode-1").passed)
        self.assertTrue(self.pipeline.run_storyboard("series-1", "episode-1").passed)
        episode = self.pipeline.get_episode("episode-1")
        for shot_id in episode.shot_ids:
            self.assertTrue(self.pipeline.run_shot("series-1", "episode-1", shot_id).passed)
        final = self.pipeline.run_audio_and_edit("series-1", "episode-1")
        self.assertTrue(final.passed)
        self.assertEqual(self.pipeline.get_episode("episode-1").status, Stage.FINAL_ACCEPTANCE)

    def test_failed_second_shot_does_not_change_first_shot(self):
        self.create_project()
        self.pipeline.run_story_and_script("series-1", "episode-1")
        self.pipeline.run_assets("series-1", "episode-1")
        self.pipeline.run_storyboard("series-1", "episode-1")
        shot_ids = self.pipeline.get_episode("episode-1").shot_ids
        self.assertGreaterEqual(len(shot_ids), 2)
        self.assertTrue(self.pipeline.run_shot("series-1", "episode-1", shot_ids[0]).passed)
        self.video.failure_mode = "timeout"
        failed = self.pipeline.run_shot("series-1", "episode-1", shot_ids[1])
        self.assertFalse(failed.passed)
        self.assertIsNotNone(self.pipeline.get_shot(shot_ids[0]).selected_media_id)
        self.assertIsNone(self.pipeline.get_shot(shot_ids[1]).selected_media_id)

    def test_series_episode_reads_previous_character_state(self):
        self.create_project()
        self.pipeline.run_story_and_script("series-1", "episode-1")
        self.pipeline.confirm_character_state("episode-1", {"char-main": "injured"})
        second = self.pipeline.create_episode("series-1", "episode-2", 2, 90, EpisodeMode.SERIES)
        result = self.pipeline.prepare_episode_from_series("series-1", second.id)
        self.assertTrue(result.passed)
        self.assertEqual(self.pipeline.get_episode(second.id).character_state["char-main"], "injured")


if __name__ == "__main__":
    unittest.main()
