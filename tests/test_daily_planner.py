import json
import subprocess
import unittest
from pathlib import Path

from sop.validators import validate_acceptance


ROOT = Path(__file__).parents[1]
APP = ROOT / "app"
FEATURE = ROOT / "features" / "daily-planner"


class DailyPlannerContractTest(unittest.TestCase):
    def test_app_assets_and_required_ui_contract_exist(self):
        for name in ("index.html", "styles.css", "app.js", "manifest.webmanifest", "sw.js"):
            self.assertTrue((APP / name).exists(), name)
        html = (APP / "index.html").read_text(encoding="utf-8")
        for marker in ("id=\"task-form\"", "id=\"timeline\"", "id=\"review-form\"", 'data-action="add-task"'):
            self.assertIn(marker, html)

    def test_acceptance_matrix_has_core_and_extended_scenarios(self):
        data = json.loads((FEATURE / "acceptance.json").read_text(encoding="utf-8"))
        errors = validate_acceptance(data["scenarios"])
        self.assertEqual(errors, [])
        self.assertGreaterEqual(len(data["scenarios"]), 10)

    def test_javascript_has_valid_syntax(self):
        result = subprocess.run(["node", "--check", str(APP / "app.js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_service_worker_and_manifest_are_well_formed(self):
        manifest = json.loads((APP / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "今日计划")
        self.assertIn("serviceWorker", (APP / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
