"""Tests for the judge_types/ folder structure.

Validates the registry, placeholder behavior, and the real
selection_summary_judge wrapper around derive_selection_summary.
"""

import unittest

import judge_types
from judge_types import (
    calibration_judge,
    coverage_judge,
    mapping_judge,
    quality_judge,
    selection_summary_judge,
)
from judge_types.reflection_judge import (
    AtlasReflectionJudge,
    derive_selection_summary,
    validate_output,
)


class RegistryTests(unittest.TestCase):
    def test_real_and_placeholder_sets_are_disjoint_and_cover_all(self) -> None:
        self.assertEqual(set(judge_types.REAL) & set(judge_types.PLACEHOLDER), set())
        self.assertEqual(set(judge_types.ALL),
                         set(judge_types.REAL) | set(judge_types.PLACEHOLDER))
        # 7 total per the canonical taxonomy.
        self.assertEqual(len(judge_types.ALL), 7)

    def test_real_judges_are_named_as_expected(self) -> None:
        self.assertIn("selection_judge", judge_types.REAL)
        self.assertIn("reflection_judge", judge_types.REAL)
        self.assertIn("selection_summary_judge", judge_types.REAL)


class PlaceholderTests(unittest.TestCase):
    def test_each_placeholder_raises_not_implemented(self) -> None:
        for mod in (mapping_judge, coverage_judge, quality_judge, calibration_judge):
            with self.assertRaises(NotImplementedError, msg=mod.__name__):
                mod.run({})


class SelectionSummaryJudgeTests(unittest.TestCase):
    def test_empty_input_returns_all_buckets(self) -> None:
        out = selection_summary_judge.run([], [])
        # All 12 canonical buckets must be present even for empty input.
        expected = {
            "root_failure_modes", "candidate_attributable_failure_modes",
            "external_or_environmental_failure_modes",
            "unrecovered_failure_modes", "recovered_failure_modes",
            "terminal_symptom_modes", "isolated_failure_modes",
            "actionable_failure_modes", "high_severity_failure_modes",
            "outcome_linked_failure_modes",
            "unmapped_failure_points", "weak_taxonomy_matches",
        }
        self.assertEqual(set(out.keys()), expected)
        for k in expected:
            self.assertEqual(out[k], [])

    def test_root_cause_with_mapping_lands_in_root_bucket(self) -> None:
        fps = [{
            "failure_point_id": "F1",
            "causal_role": "root_cause",
            "recovery_status": "unrecovered",
            "actionability": "high",
            "severity": "critical",
            "outcome_link": "direct",
            "candidate_attribution": "high",
            "external_attribution": "none",
            "taxonomy_mappings": [
                {"code": "A.1", "primary_or_secondary": "primary",
                 "mapping_confidence": 0.9}
            ],
        }]
        out = selection_summary_judge.run(fps)
        self.assertIn("A.1", out["root_failure_modes"])
        self.assertIn("A.1", out["unrecovered_failure_modes"])
        self.assertIn("A.1", out["actionable_failure_modes"])
        self.assertIn("A.1", out["high_severity_failure_modes"])

    def test_weak_mapping_below_threshold_surfaces(self) -> None:
        fps = [{
            "failure_point_id": "F1",
            "causal_role": "unclear",
            "recovery_status": "not_applicable",
            "actionability": "low",
            "severity": "minor",
            "outcome_link": "unlikely",
            "candidate_attribution": "low",
            "external_attribution": "none",
            "taxonomy_mappings": [
                {"code": "A.2", "primary_or_secondary": "primary",
                 "mapping_confidence": 0.3,
                 "mapping_rationale": "weak fit"}
            ],
        }]
        out = selection_summary_judge.run(fps, weak_threshold=0.5)
        weak = out["weak_taxonomy_matches"]
        self.assertEqual(len(weak), 1)
        self.assertEqual(weak[0]["code"], "A.2")


class ReflectionJudgeShellTests(unittest.TestCase):
    """Construct the judge with a stub LLM to confirm wiring works.

    We don't exercise the prompt — that would mean an LLM call. The point is
    to prove import/construction is sane and that the public surface matches
    the GEPA original (sans hardcoded model default).
    """

    def test_requires_judge_model(self) -> None:
        from atlas_runtime.taxonomy_data import Taxonomy
        tax = Taxonomy.from_flat({"repo": "x", "domain": "y", "codes": []})
        with self.assertRaises(ValueError):
            AtlasReflectionJudge(tax, judge_model="")

    def test_rejects_unknown_mode(self) -> None:
        from atlas_runtime.taxonomy_data import Taxonomy
        tax = Taxonomy.from_flat({"repo": "x", "domain": "y", "codes": []})
        with self.assertRaises(ValueError):
            AtlasReflectionJudge(tax, judge_model="m", mode="bogus")

    def test_analyze_with_stub_llm_returns_envelope(self) -> None:
        from atlas_runtime.taxonomy_data import Taxonomy
        tax = Taxonomy.from_flat({"repo": "x", "domain": "y", "codes": []})

        def stub_llm(user, system, *, max_tokens=8192, meter=None, warnings=None):
            # Trivially valid analysis result with zero failure points.
            return {
                "trace_summary": {"overall_judgment": "success"},
                "events": [],
                "failure_points": [],
                "relations": [],
            }

        judge = AtlasReflectionJudge(tax, judge_model="stub", llm_call=stub_llm)
        out = judge.analyze({
            "candidate_id": "c", "task_id": "t", "run_id": "r",
            "task_prompt": "do thing", "candidate_output": "result",
            "trace": "...",
        })
        self.assertEqual(out["candidate_id"], "c")
        self.assertEqual(out["judge_metadata"]["judge_model"], "stub")
        self.assertEqual(out["failure_points"], [])
        # selection_summary must be the deterministic derivation, not from LLM.
        self.assertIn("root_failure_modes", out["selection_summary"])


class SchemaValidatorTests(unittest.TestCase):
    def test_validate_output_flags_missing_top_level(self) -> None:
        errs = validate_output({})
        self.assertTrue(errs)

    def test_validate_output_accepts_minimal_valid_envelope(self) -> None:
        envelope = {
            "candidate_id": "c", "task_id": "t", "run_id": "r",
            "judge_metadata": {},
            "trace_summary": {"overall_judgment": "success"},
            "events": [],
            "failure_points": [],
            "relations": [],
            "selection_summary": {},
            "reflection_summary": {},
        }
        self.assertEqual(validate_output(envelope), [])


class DeriveSelectionSummaryTests(unittest.TestCase):
    """The selection.py module is a pure function — exercise it directly too."""

    def test_unmapped_failure_point_recorded(self) -> None:
        fps = [{
            "failure_point_id": "F1",
            "causal_role": "root_cause",
            "recovery_status": "unrecovered",
            "actionability": "high",
            "severity": "critical",
            "outcome_link": "direct",
            "candidate_attribution": "high",
            "external_attribution": "none",
            "taxonomy_mappings": [],
            "unmapped": True,
            "proposed_failure_mode": {"name": "NewMode", "definition": "..."},
            "ruled_out_codes": [{"code": "A.1", "reason": "doesn't fit"}],
        }]
        out = derive_selection_summary(fps)
        self.assertEqual(len(out["unmapped_failure_points"]), 1)
        self.assertEqual(out["unmapped_failure_points"][0]["proposed_name"], "NewMode")


if __name__ == "__main__":
    unittest.main()
