import json
import shutil
import tempfile
import unittest
from pathlib import Path

from sop.engine import Workflow
from sop.errors import GateError
from sop.models import State


class MangaWorkflowIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent.parent
        self.workflow = Workflow(self.root)

    def test_manga_spec_is_frozen_before_development(self):
        state = self.workflow.load("ai-manga-pipeline")
        self.assertIn(state.state, (State.DEVELOPMENT, State.SELF_TESTED, State.ACCEPTANCE, State.DONE))
        self.assertEqual(
            set(state.protected_hashes),
            {"requirements.md", "spec.md", "plan.md", "acceptance.json"},
        )

    def test_development_cannot_enter_self_test_without_aa_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            shutil.copytree(self.root / "features" / "ai-manga-pipeline", temp_root / "features" / "ai-manga-pipeline")
            evidence = temp_root / "features" / "ai-manga-pipeline" / "aa" / "self-test.json"
            evidence.unlink()
            state_path = temp_root / "features" / "ai-manga-pipeline" / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["state"] = State.DEVELOPMENT.value
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(GateError):
                Workflow(temp_root).advance("ai-manga-pipeline", State.SELF_TESTED)

    def test_protected_spec_hashes_still_match(self):
        state = self.workflow.load("ai-manga-pipeline")
        self.workflow._check_hashes(state)


if __name__ == "__main__":
    unittest.main()
