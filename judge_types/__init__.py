"""ATLAS skill judge types.

A canonical catalog of the seven taxonomy-aware judges atlas_skill exposes
(or stubs). Each judge consumes a taxonomy and produces a different
structured signal:

  1. **SelectionJudge** — trace + taxonomy -> flat failure-mode labels.
     Shallow, scalable, used for search/selection. Real implementation wraps
     ``atlas_runtime.taxonomy_check``.

  2. **ReflectionJudge** — trace + taxonomy -> failure-point graph + taxonomy
     mappings. Deep, causal, used for mutation/reflection/debugging. Real
     implementation lives in ``judge_types.reflection_judge`` (ported from
     GEPA's ``atlas_reflection_judge``).

  3. **MappingJudge** — failure_point + taxonomy -> best code(s). Modular
     sub-judge; useful when failure-point identification and code-assignment
     are split. Placeholder for now.

  4. **CoverageJudge** — trace or failure_point + taxonomy -> covered /
     partially / missing. Drives taxonomy expansion. Placeholder for now.

  5. **QualityJudge** — taxonomy + support traces -> codebook quality
     feedback. Evaluates codes (not traces). Placeholder for now.

  6. **CalibrationJudge** — annotation + evidence + taxonomy -> reliability of
     a code assignment. Audits the Selection Judge. Placeholder for now.

  7. **SelectionSummaryJudge** — taxonomy-labeled failures -> compressed
     selection signal (root / candidate-attributable / unrecovered / terminal /
     actionable / external buckets). Real implementation wraps
     ``judge_types.reflection_judge.selection.derive_selection_summary``.

Module-level constants ``REAL`` and ``PLACEHOLDER`` enumerate which judges
currently have working implementations vs. stubs raising NotImplementedError.
"""

from __future__ import annotations

REAL = ("reflection_judge", "selection_summary_judge")
PLACEHOLDER = (
    "selection_judge",
    "mapping_judge",
    "coverage_judge",
    "quality_judge",
    "calibration_judge",
)
ALL = REAL + PLACEHOLDER

__all__ = ["REAL", "PLACEHOLDER", "ALL"]
