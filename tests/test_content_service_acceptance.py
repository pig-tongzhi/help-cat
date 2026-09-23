import json
import tempfile
import unittest
from pathlib import Path

from sop.content_service_acceptance import run_acceptance


class ContentServiceAcceptanceTest(unittest.TestCase):
    def test_independent_acceptance_covers_frozen_matrix_without_network(self):
        with tempfile.TemporaryDirectory() as runtime:
            result = run_acceptance(Path("features/short-video-content-service"), Path(runtime))
        matrix = json.loads(Path("features/short-video-content-service/acceptance.json").read_text(encoding="utf-8"))
        self.assertTrue(result["passed"], result["defects"])
        self.assertEqual(result["scenario_coverage"], 100)
        self.assertEqual({item["id"] for item in result["scenario_results"]}, {item["id"] for item in matrix["scenarios"]})
        self.assertEqual(result["external_effects"]["real_network_calls"], 0)
        self.assertEqual(result["db_snapshot"]["failed_case_exported_after"], 0)


if __name__ == "__main__":
    unittest.main()
