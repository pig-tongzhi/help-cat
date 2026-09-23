import unittest

from sop.rescue_models import (
    ReportType,
    TnrStatus,
    TaskStatus,
    validate_positive_quantity,
    validate_report_payload,
    can_transition_task,
    can_transition_tnr,
)


class RescueModelTests(unittest.TestCase):
    def test_valid_report_payload_is_accepted(self):
        validate_report_payload({"title": "银湖小区橘猫受伤", "type": ReportType.INJURY.value})

    def test_blank_report_title_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_report_payload({"title": "  ", "type": ReportType.INJURY.value})

    def test_supply_quantity_must_be_positive_integer(self):
        self.assertEqual(validate_positive_quantity("3"), 3)
        with self.assertRaises(ValueError):
            validate_positive_quantity(0)
        with self.assertRaises(ValueError):
            validate_positive_quantity("1.5")

    def test_task_can_move_forward_but_not_back_from_done(self):
        self.assertTrue(can_transition_task(TaskStatus.OPEN, TaskStatus.CLAIMED))
        self.assertFalse(can_transition_task(TaskStatus.DONE, TaskStatus.OPEN))

    def test_tnr_requires_explicit_forward_states(self):
        self.assertTrue(can_transition_tnr(TnrStatus.CAUGHT, TnrStatus.STERILIZED))
        self.assertFalse(can_transition_tnr(TnrStatus.RELEASED, TnrStatus.CAUGHT))


if __name__ == "__main__":
    unittest.main()
