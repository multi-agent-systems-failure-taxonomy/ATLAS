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

    def test_markdown_ready_status_allows(self):
        decision = protocol.evaluate_pre_submission(
            "# Final ATLAS Status\n\n"
            "**Repair attempts used:** 2\n\n"
            "**Status:** Ready for release\n\n"
            "## Proposed Final Answer\n\n"
            "2 + 2 = 4\n"
        )
        self.assertTrue(decision.allow)
        self.assertEqual(decision.status, protocol.READY)
        self.assertEqual(decision.repair_attempts_used, 2)

    def test_final_decision_submit_allows(self):
        decision = protocol.evaluate_pre_submission(
            "ATLAS reflection:\n"
            "- Decide: no change needed, because verification is complete.\n\n"
            "Final decision: submit\n"
            "Repair attempts used: 1\n"
        )
        self.assertTrue(decision.allow)
        self.assertEqual(decision.status, protocol.READY)

    def test_markdown_task_complete_status_allows(self):
        decision = protocol.evaluate_pre_submission(
            "**Final ATLAS status:** Task complete. Computation verified. "
            "Final answer: **4**\n"
            "**Repair attempts used:** 2\n"
        )
        self.assertTrue(decision.allow)
        self.assertEqual(decision.status, protocol.READY)
        self.assertEqual(decision.repair_attempts_used, 2)

    def test_final_status_pass_allows(self):
        decision = protocol.evaluate_pre_submission(
            "Final ATLAS status: PASS\n\n"
            "Answer: 4\n"
        )
        self.assertTrue(decision.allow)
        self.assertEqual(decision.status, protocol.READY)

    def test_gate_outcome_pass_allows(self):
        decision = protocol.evaluate_pre_submission(
            "## Final ATLAS status:\n\n"
            "**Gate outcome:** PASS\n\n"
            "**Repair attempts used:** 2\n\n"
            "Answer: 4\n"
        )
        self.assertTrue(decision.allow)
        self.assertEqual(decision.status, protocol.READY)
        self.assertEqual(decision.repair_attempts_used, 2)

    def test_decide_no_change_can_stand_in_for_status(self):
        decision = protocol.evaluate_pre_submission(
            "ATLAS reflection:\n"
            "- Checkpoint ID: abc\n"
            "- Observe: verified\n"
            "- Map:\n"
            "  - none apply | considered: MAST-12 | evidence: \"verified\"\n"
            "- Correlate: no failure\n"
            "- Decide: no change needed, because the answer is verified.\n"
            "\nRepair attempts used: 1\n"
        )
        self.assertTrue(decision.allow)
        self.assertEqual(decision.status, protocol.READY)
        self.assertEqual(decision.repair_attempts_used, 1)

    def test_positive_status_phrase_allows(self):
        decision = protocol.evaluate_pre_submission(
            "## Final ATLAS status:\n\n"
            "**Status:** GATE CLEARANCE PROPERLY AWAITED\n"
            "**Task compliance:** Current state is compliant with specification\n"
            "**Repair attempts used:** 2\n"
        )
        self.assertTrue(decision.allow)
        self.assertEqual(decision.status, protocol.READY)

    def test_bare_line_after_final_status_heading_allows(self):
        decision = protocol.evaluate_pre_submission(
            "## Final ATLAS status\n\n"
            "Ready for final answer.\n\n"
            "**Codes checked:** none\n"
            "**Repair attempts used:** 1\n"
        )
        self.assertTrue(decision.allow)
        self.assertEqual(decision.status, protocol.READY)
        self.assertEqual(decision.repair_attempts_used, 1)

    def test_no_failure_modes_ready_phrase_allows(self):
        decision = protocol.evaluate_pre_submission(
            "Final ATLAS status: No failure modes remain; ready to submit.\n"
            "Repair attempts used: 0\n"
        )
        self.assertTrue(decision.allow)
        self.assertEqual(decision.status, protocol.READY)

    def test_decide_change_blocks_as_repair(self):
        decision = protocol.evaluate_pre_submission(
            "ATLAS reflection:\n"
            "- Decide: change: run the missing verification.\n"
            "\nRepair attempts used: 1\n",
            max_retries=3,
        )
        self.assertFalse(decision.allow)
        self.assertEqual(decision.status, protocol.REPAIR)

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

    def test_markdown_repair_status_blocks(self):
        decision = protocol.evaluate_pre_submission(
            "## Final ATLAS Status\n\n"
            "- **Status:** needs repair\n"
            "- **Repair attempts used:** 1\n",
            max_retries=3,
        )
        self.assertFalse(decision.allow)
        self.assertEqual(decision.status, protocol.REPAIR)
        self.assertIn("2 attempt(s) remain", decision.reason)

    def test_pin_gate_decision_suppresses_a_flip(self):
        emitted = protocol.evaluate_pre_submission(
            "Final ATLAS status: REPAIR_REQUIRED\nRepair attempts used: 0",
            max_retries=3,
        )
        pinned, flipped = protocol.pin_gate_decision(
            emitted, protocol.READY, max_retries=3
        )
        self.assertTrue(flipped)
        self.assertTrue(pinned.allow)
        self.assertEqual(pinned.status, protocol.READY)
        self.assertIn("verdict pinned", pinned.reason)

    def test_pin_gate_decision_pins_repair_over_ready(self):
        emitted = protocol.evaluate_pre_submission(
            "Final ATLAS status: READY_TO_SUBMIT\nRepair attempts used: 0",
            max_retries=3,
        )
        pinned, flipped = protocol.pin_gate_decision(
            emitted, protocol.REPAIR, max_retries=3
        )
        self.assertTrue(flipped)
        self.assertFalse(pinned.allow)
        self.assertEqual(pinned.status, protocol.REPAIR)

    def test_pin_gate_decision_noop_cases(self):
        emitted = protocol.evaluate_pre_submission(
            "Final ATLAS status: READY_TO_SUBMIT\nRepair attempts used: 0",
            max_retries=3,
        )
        same, flipped = protocol.pin_gate_decision(
            emitted, protocol.READY, max_retries=3
        )
        self.assertFalse(flipped)
        self.assertIs(same, emitted)

        none_pinned, flipped = protocol.pin_gate_decision(
            emitted, None, max_retries=3
        )
        self.assertFalse(flipped)
        self.assertIs(none_pinned, emitted)

        missing = protocol.evaluate_pre_submission("done", max_retries=3)
        unchanged, flipped = protocol.pin_gate_decision(
            missing, protocol.READY, max_retries=3
        )
        self.assertFalse(flipped)
        self.assertIs(unchanged, missing)


    def test_failure_statuses_containing_success_substrings_block(self):
        # Regression: "incomplete"/"unsuccessful"/"not passed" must not be
        # normalized to READY just because they contain complete/success/pass.
        for status in ("incomplete", "unsuccessful", "not passed", "not verified"):
            self.assertEqual(
                protocol._normalize_status(status),
                protocol.REPAIR,
                msg=f"{status!r} should block, not approve",
            )
            decision = protocol.evaluate_pre_submission(
                f"Final ATLAS status: {status}\nRepair attempts used: 0\n"
            )
            self.assertFalse(decision.allow, msg=f"gate approved {status!r}")

    def test_genuine_success_statuses_still_allow(self):
        for status in ("READY_TO_SUBMIT", "complete", "verified", "passed"):
            self.assertEqual(protocol._normalize_status(status), protocol.READY)


if __name__ == "__main__":
    unittest.main()
