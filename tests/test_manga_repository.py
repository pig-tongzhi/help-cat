import tempfile
import unittest
from pathlib import Path

from sop.manga_models import Episode, EpisodeMode, GenerationRun, RunStatus, Series, SourceType, Stage
from sop.manga_repository import ConcurrentCommitError, MangaRepository


class MangaRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = MangaRepository(Path(self.temp_dir.name))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_version_save_and_atomic_current_commit(self):
        series = Series.create("series-1", "测试", SourceType.ORIGINAL)
        version = self.repo.save_series(series)
        self.assertIsNone(self.repo.current_version("series", series.id))
        self.repo.commit_current("series", series.id, version)
        self.assertEqual(self.repo.current_version("series", series.id), version)

    def test_expected_current_prevents_lost_update(self):
        series = Series.create("series-1", "测试", SourceType.ORIGINAL)
        first = self.repo.save_series(series)
        self.repo.commit_current("series", series.id, first)
        second = self.repo.save_series(Series.create("series-1", "新标题", SourceType.ORIGINAL))
        with self.assertRaises(ConcurrentCommitError):
            self.repo.commit_current("series", series.id, second, expected_current="wrong")

    def test_idempotency_key_reuses_existing_run(self):
        first = self.repo.acquire_idempotency("same-key")
        second = self.repo.acquire_idempotency("same-key")
        self.assertEqual(first, second)

    def test_failed_version_can_roll_back_to_prior_current(self):
        series = Series.create("series-1", "测试", SourceType.ORIGINAL)
        first = self.repo.save_series(series)
        second = self.repo.save_series(Series.create("series-1", "失败版本", SourceType.ORIGINAL))
        self.repo.commit_current("series", series.id, first)
        self.repo.rollback_current("series", series.id, first)
        self.assertEqual(self.repo.current_version("series", series.id), first)
        self.assertNotEqual(first, second)

    def test_run_evidence_round_trips(self):
        run = GenerationRun(
            "run-1", Stage.SCRIPTING, "episode-1", "input", "idem", RunStatus.SUCCEEDED, "fake", "v1"
        )
        self.repo.write_run(run)
        self.assertEqual(self.repo.read_run(run.id).to_dict(), run.to_dict())


if __name__ == "__main__":
    unittest.main()
