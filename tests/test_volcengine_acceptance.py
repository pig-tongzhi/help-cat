import json
import tempfile
import unittest
from pathlib import Path

from sop.volcengine_acceptance import run_acceptance


class VolcengineAcceptanceTest(unittest.TestCase):
    def test_provider_matrix_passes_without_network(self):
        feature_dir = Path(__file__).parent.parent / "features" / "volcengine-video-provider"
        with tempfile.TemporaryDirectory() as runtime:
            report = run_acceptance(feature_dir, Path(runtime))
        self.assertTrue(report["passed"], report["defects"])
        self.assertEqual(report["scenario_coverage"], 100)
        self.assertEqual(len(report["scenario_results"]), 20)
        self.assertEqual(report["external_effects"]["real_network_calls"], 0)


if __name__ == "__main__":
    unittest.main()
