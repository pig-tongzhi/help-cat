import unittest

from sop.manga_models import (
    Asset,
    Episode,
    EpisodeMode,
    Series,
    SourceType,
    StoryEvent,
    stable_id,
)


class MangaModelTest(unittest.TestCase):
    def test_stable_id_is_reproducible_and_namespaced(self):
        first = stable_id("shot", "ep-1", "1")
        second = stable_id("shot", "ep-1", "1")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("shot-"))

    def test_series_rejects_unknown_source_type(self):
        with self.assertRaises(ValueError):
            Series.create("s1", "title", "UNAUTHORIZED")

    def test_series_and_episode_keep_single_or_series_mode(self):
        series = Series.create("s1", "title", SourceType.ORIGINAL)
        single = Episode.create("e1", series.id, 1, 90, EpisodeMode.SINGLE)
        serial = Episode.create("e2", series.id, 2, 120, EpisodeMode.SERIES)
        self.assertEqual(single.episode_no, 1)
        self.assertEqual(serial.mode, EpisodeMode.SERIES)

    def test_entities_serialize_canonically(self):
        event = StoryEvent(id="event-1", title="开门", objective="进入房间", outcome="发现线索")
        asset = Asset(
            id="asset-1",
            kind="character",
            name="主角",
            description="短发青年",
            version="v1",
            immutable_traits=("黑发",),
            mutable_traits=("表情",),
        )
        payload = asset.to_dict()
        self.assertEqual(payload["immutable_traits"], ["黑发"])
        self.assertEqual(event.to_dict()["title"], "开门")

    def test_episode_rejects_invalid_duration(self):
        with self.assertRaises(ValueError):
            Episode.create("e1", "s1", 1, 29, EpisodeMode.SINGLE)


if __name__ == "__main__":
    unittest.main()
