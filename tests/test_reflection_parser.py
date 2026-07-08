"""Focused tests for tolerant-but-safe ATLAS reflection parsing."""

from __future__ import annotations

import unittest

from atlas_runtime.reflection import parse_reflection


class ReflectionParserTests(unittest.TestCase):
    def test_accepts_markdown_heading_checkpoint_and_section_synonyms(self):
        result = parse_reflection(
            """# ATLAS reflection

## Checkpoint ID: cp-1

## Observation
The run skipped verification.

## Mapping
- MAST-12 | Verification gap | evidence: "no tests were run"

## Root causes
The agent treated implementation as enough.

## Decision
change to run the relevant test before submission
""",
            checkpoint_id="cp-1",
            known_code_ids=("MAST-12",),
        )
        self.assertEqual(result.assignments[0].code_id, "MAST-12")
        self.assertIn("no tests", result.assignments[0].evidence)
        self.assertIn("change", result.decide)

    def test_still_requires_matching_checkpoint_id(self):
        with self.assertRaisesRegex(ValueError, "Checkpoint ID"):
            parse_reflection(
                """ATLAS reflection:
- Observe: checked
- Map:
  - MAST-12 | evidence: "missing verification"
- Correlate: skipped
- Decide: change: verify
""",
                checkpoint_id="cp-1",
                known_code_ids=("MAST-12",),
            )

    def test_accepts_evidence_is_form(self):
        result = parse_reflection(
            """ATLAS reflection:
- Checkpoint ID: cp-2
- Observe: checked
- Mapping:
  - MAST-12 | evidence is "the final answer lacks validation"
- Causal: rushed completion
- Action: change: validate first
""",
            checkpoint_id="cp-2",
            known_code_ids=("MAST-12",),
        )
        self.assertEqual(
            result.assignments[0].evidence,
            "the final answer lacks validation",
        )

    def test_accepts_clean_map_with_codes_checked_summary(self):
        result = parse_reflection(
            """ATLAS reflection:
- Checkpoint ID: cp-3
- Observe: The task is complete and no failure evidence is present.
- Map:
  - none apply | evidence: "No failure evidence is present."
- Correlate: No recurring failure pattern is visible.
- Decide: submit: no change needed.

Final ATLAS status: READY_TO_SUBMIT
Codes checked: MAST-1, MAST-12
Evidence: No failure evidence is present.
Final decision: ready
""",
            checkpoint_id="cp-3",
            known_code_ids=("MAST-1", "MAST-12"),
        )
        self.assertTrue(result.none_apply)
        self.assertEqual(result.assignments, ())
        self.assertEqual(result.considered_codes, ("MAST-1", "MAST-12"))


if __name__ == "__main__":
    unittest.main()
