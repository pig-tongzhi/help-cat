import json
import tempfile
import unittest
from pathlib import Path

from sop.manga_acceptance import run_acceptance


class MangaAcceptanceTest(unittest.TestCase):
    def test_frozen_matrix_runs_in_fresh_runtime_with_full_coverage(self):
        feature_dir = Path(__file__).parent.parent / "features" / "ai-manga-pipeline"
        with tempfile.TemporaryDirectory() as runtime_dir:
            report = run_acceptance(feature_dir, Path(runtime_dir))
        self.assertTrue(report["passed"], report["defects"])
        self.assertEqual(report["scenario_coverage"], 100)
        self.assertEqual(len(report["scenario_results"]), 30)
        self.assertTrue(all(item["passed"] for item in report["scenario_results"]))
        self.assertIn("before", report["db_snapshot"])
        self.assertIn("after", report["db_snapshot"])

    def test_missing_scenario_is_reported_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            feature_dir = Path(temp_dir)
            (feature_dir / "acceptance.json").write_text(
                json.dumps({"scenarios": [{"id": "AC-999", "category": "positive", "title": "未知"}]}),
                encoding="utf-8",
            )
            report = run_acceptance(feature_dir, feature_dir / "runtime")
        self.assertFalse(report["passed"])
        self.assertEqual(report["scenario_coverage"], 0)
        self.assertEqual(report["scenario_results"][0]["error"], "UNSUPPORTED_SCENARIO")


if __name__ == "__main__":
    unittest.main()
