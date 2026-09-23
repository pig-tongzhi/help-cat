import unittest

from sop.manga_models import (
    Asset,
    Dialogue,
    Episode,
    EpisodeMode,
    Series,
    Shot,
    SourceType,
    StoryEvent,
)
from sop.manga_validation import (
    validate_project_input,
    validate_script_counterfactual,
    validate_script_positive,
    validate_series_continuity,
)


def make_series_and_episode():
    character = Asset("char-1", "character", "主角", "黑发青年", "v1")
    location = Asset("loc-1", "location", "房间", "昏暗房间", "v1")
    event = StoryEvent("event-1", "开门", "进入房间", "发现线索", character_ids=(character.id,), location_id=location.id)
    series = Series(
        "series-1",
        "测试故事",
        SourceType.ORIGINAL,
        characters=(character,),
        locations=(location,),
        story_events=(event,),
    )
    episode = Episode.create("episode-1", series.id, 1, 90, EpisodeMode.SINGLE)
    return series, episode, character, location, event


class MangaValidationTest(unittest.TestCase):
    def test_project_input_boundaries(self):
        self.assertEqual(
            validate_project_input("x" * 20, "ORIGINAL", 30, "SINGLE", 1, "zh-CN", "9:16", "动漫"), []
        )
        self.assertTrue(validate_project_input("x" * 19, "ORIGINAL", 30, "SINGLE", 1, "zh-CN", "9:16", "动漫"))
        self.assertTrue(validate_project_input("x" * 20, "ORIGINAL", 601, "SINGLE", 1, "zh-CN", "9:16", "动漫"))

    def test_positive_script_requires_known_speakers_and_event_links(self):
        series, episode, character, location, event = make_series_and_episode()
        shot = Shot(
            "shot-1", episode.id, (event.id,), (character.id,), location.id,
            "开门", "近景", 4, (Dialogue(character.id, "你终于来了。"),),
        )
        valid = validate_script_positive(series, episode, shots=(shot,))
        self.assertEqual(valid, [])
        invalid = Shot(
            "shot-2", episode.id, (event.id,), (character.id,), location.id,
            "开门", "近景", 4, (Dialogue("unknown", "我知道一切。"),),
        )
        errors = validate_script_positive(series, episode, shots=(invalid,))
        self.assertIn("SCRIPT_UNKNOWN_SPEAKER", errors)

    def test_counterfactual_detects_missing_prerequisite_event(self):
        character = Asset("char-1", "character", "主角", "黑发青年", "v1")
        event = StoryEvent("event-2", "使用钥匙", "打开门", "门打开", prerequisite_event_ids=("event-missing",), character_ids=(character.id,))
        series = Series("series-1", "测试", SourceType.ORIGINAL, characters=(character,), story_events=(event,))
        episode = Episode.create("episode-1", series.id, 1, 90, EpisodeMode.SINGLE)
        errors = validate_script_counterfactual(series, episode)
        self.assertIn("SCRIPT_MISSING_CAUSE", errors)

    def test_continuity_rejects_unapproved_character_state_change(self):
        series, previous, _, _, _ = make_series_and_episode()
        current = Episode.create("episode-2", series.id, 2, 90, EpisodeMode.SERIES)
        previous = Episode(
            previous.id, previous.series_id, previous.episode_no, previous.target_duration_sec,
            previous.mode, character_state={"char-1": "injured"},
        )
        current = Episode(
            current.id, current.series_id, current.episode_no, current.target_duration_sec,
            current.mode, character_state={"char-1": "healthy"},
        )
        errors = validate_series_continuity(previous, current, series)
        self.assertIn("SERIES_STATE_CONFLICT", errors)


if __name__ == "__main__":
    unittest.main()
