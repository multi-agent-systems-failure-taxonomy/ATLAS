"""Minimal pre-submission gate tests."""

import unittest

from atlas_runtime import protocol


class ProtocolTests(unittest.TestCase):
    def test_runtime_protocol_has_gate_and_retry_but_no_checkpoints(self):
        text = protocol.render_protocol(max_retries=3)
        self.assertIn("Final ATLAS status:", text)
        self.assertIn("at most 3 repair attempts", text)
        self.assertNotIn("checkpoint", text.lower())
        self.assertNotIn("Task domain:", text)

    def test_missing_gate_blocks(self):
        decision = protocol.evaluate_pre_submission("done")
        self.assertFalse(decision.allow)
        self.assertEqual(decision.decision, "block")

    def test_ready_allows(self):
        decision = protocol.evaluate_pre_submission(
            "Final ATLAS status: READY_TO_SUBMIT\n"
            "Repair attempts used: 0\n"
        )
        self.assertTrue(decision.allow)
        self.assertEqual(decision.decision, "approve")

    def test_repair_required_blocks_while_budget_remains(self):
        decision = protocol.evaluate_pre_submission(
            "Final ATLAS status: REPAIR_REQUIRED\n"
            "Repair attempts used: 1\n",
            max_retries=3,
        )
        self.assertFalse(decision.allow)
        self.assertIn("2 attempt(s) remain", decision.reason)

    def test_repair_required_allows_honest_report_at_cap(self):
        decision = protocol.evaluate_pre_submission(
            "Final ATLAS status: REPAIR_REQUIRED\n"
            "Repair attempts used: 3\n",
            max_retries=3,
        )
        self.assertTrue(decision.allow)
        self.assertEqual(decision.decision, "approve_unresolved")


if __name__ == "__main__":
    unittest.main()
