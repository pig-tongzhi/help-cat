import json
import tempfile
import unittest
from pathlib import Path

from sop.engine import Workflow
from sop.errors import GateError, StateTransitionError, SpecTamperedError
from sop.models import State
from sop.validators import validate_acceptance


def acceptance_matrix():
    return [
        {"id": "AC-001", "category": "positive", "title": "happy path"},
        {"id": "AC-002", "category": "negative", "title": "reject invalid input"},
        {"id": "AC-003", "category": "database", "title": "preserve database invariant"},
    ]


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.workflow = Workflow(self.root)
        self.feature = "order-create"

    def tearDown(self):
        self.tempdir.cleanup()

    def seed_complete_package(self):
        self.workflow.create(self.feature, "Create a payable order and freeze stock")
        feature_dir = self.root / "features" / self.feature
        for name in ("requirements.md", "research.md", "spec.md", "plan.md", "tasks.md"):
            (feature_dir / name).write_text(f"# {name}\nComplete and reviewable.\n", encoding="utf-8")
        (feature_dir / "acceptance.json").write_text(
            json.dumps({"version": 1, "scenarios": acceptance_matrix()}), encoding="utf-8"
        )
        (feature_dir / "aa" / "self-test.json").write_text(
            json.dumps({
                "compile": True,
                "unit": True,
                "repository": True,
                "integration": True,
                "static": True,
                "acceptance_coverage": True,
            }),
            encoding="utf-8",
        )
        (feature_dir / "reports" / "acceptance.json").write_text(
            json.dumps({"passed": True, "scenario_coverage": 100}), encoding="utf-8"
        )

    def test_valid_package_can_reach_done_only_after_acceptance(self):
        self.seed_complete_package()
        self.workflow.advance(self.feature, State.RESEARCHED)
        self.workflow.advance(self.feature, State.SPECIFIED)
        self.workflow.freeze(self.feature)
        self.workflow.advance(self.feature, State.SPEC_VALIDATED)
        self.workflow.advance(self.feature, State.DEVELOPMENT)
        self.workflow.advance(self.feature, State.SELF_TESTED)
        self.workflow.advance(self.feature, State.ACCEPTANCE)
        self.workflow.accept(self.feature, passed=True)

        self.assertEqual(self.workflow.load(self.feature).state, State.DONE)

    def test_specification_gate_rejects_missing_required_artifact(self):
        self.workflow.create(self.feature, "Create an order")
        (self.root / "features" / self.feature / "research.md").unlink()
        with self.assertRaises(GateError):
            self.workflow.advance(self.feature, State.RESEARCHED)

    def test_acceptance_matrix_requires_core_categories_and_unique_ids(self):
        invalid = [
            {"id": "AC-001", "category": "positive", "title": "one"},
            {"id": "AC-001", "category": "positive", "title": "duplicate"},
        ]
        errors = validate_acceptance(invalid)
        self.assertIn("duplicate scenario id: AC-001", errors)
        self.assertIn("missing required category: negative", errors)
        self.assertIn("missing required category: database", errors)

    def test_freeze_detects_protected_spec_tampering(self):
        self.seed_complete_package()
        self.workflow.advance(self.feature, State.RESEARCHED)
        self.workflow.advance(self.feature, State.SPECIFIED)
        self.workflow.freeze(self.feature)
        spec = self.root / "features" / self.feature / "spec.md"
        spec.write_text(spec.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
        with self.assertRaises(SpecTamperedError):
            self.workflow.advance(self.feature, State.SPEC_VALIDATED)

    def test_three_failed_acceptance_rounds_stop_the_task(self):
        self.seed_complete_package()
        self.workflow.advance(self.feature, State.RESEARCHED)
        self.workflow.advance(self.feature, State.SPECIFIED)
        self.workflow.freeze(self.feature)
        self.workflow.advance(self.feature, State.SPEC_VALIDATED)
        self.workflow.advance(self.feature, State.DEVELOPMENT)
        self.workflow.advance(self.feature, State.SELF_TESTED)
        for round_number in range(1, 4):
            self.workflow.advance(self.feature, State.ACCEPTANCE)
            self.workflow.accept(self.feature, passed=False, reason=f"failure {round_number}")
            if round_number < 3:
                self.workflow.advance(self.feature, State.FIXING)
                self.workflow.advance(self.feature, State.SELF_TESTED)
        self.assertEqual(self.workflow.load(self.feature).state, State.STOPPED)

    def test_done_requires_independent_acceptance_evidence(self):
        self.seed_complete_package()
        (self.root / "features" / self.feature / "reports" / "acceptance.json").unlink()
        self.workflow.advance(self.feature, State.RESEARCHED)
        self.workflow.advance(self.feature, State.SPECIFIED)
        self.workflow.freeze(self.feature)
        self.workflow.advance(self.feature, State.SPEC_VALIDATED)
        self.workflow.advance(self.feature, State.DEVELOPMENT)
        self.workflow.advance(self.feature, State.SELF_TESTED)
        self.workflow.advance(self.feature, State.ACCEPTANCE)
        with self.assertRaises(GateError):
            self.workflow.accept(self.feature, passed=True)

    def test_illegal_transition_is_rejected(self):
        self.workflow.create(self.feature, "Create an order")
        with self.assertRaises(StateTransitionError):
            self.workflow.advance(self.feature, State.DONE)


if __name__ == "__main__":
    unittest.main()
