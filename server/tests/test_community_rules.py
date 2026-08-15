import unittest

from server.helpcat.community_rules import normalize_community_name


class CommunityRuleTests(unittest.TestCase):
    def test_normalize_community_name_collapses_width_case_and_punctuation(self):
        self.assertEqual(normalize_community_name("  星河　家园！ "), "星河家园")
        self.assertEqual(normalize_community_name("XING He"), "xinghe")

    def test_normalize_community_name_rejects_empty_result(self):
        with self.assertRaises(ValueError):
            normalize_community_name(" ！？— ")


if __name__ == "__main__":
    unittest.main()
