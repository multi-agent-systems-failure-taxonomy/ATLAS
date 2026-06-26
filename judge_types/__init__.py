"""ATLAS skill judge types.

A canonical catalog of the seven taxonomy-aware judges atlas_skill exposes.
Each judge consumes a taxonomy and produces a different structured signal:

  1. **SelectionJudge** — trace + taxonomy -> flat failure-mode labels.
     Shallow, scalable, used for search/selection.

  2. **ReflectionJudge** — trace + taxonomy -> failure-point graph + taxonomy
     mappings. Deep, causal, used for mutation/reflection/debugging. Real
     implementation lives in ``judge_types.reflection_judge``.

  3. **MappingJudge** — failure_point + taxonomy -> best code(s). Modular
     sub-judge; useful when failure-point identification and code-assignment
     are split.

  4. **CoverageJudge** — trace or failure_point + taxonomy -> covered /
     partially / missing. Drives taxonomy expansion.

  5. **QualityJudge** — taxonomy + support traces -> codebook quality
     feedback. Evaluates codes (not traces).

  6. **CalibrationJudge** — annotation + evidence + taxonomy -> reliability of
     a code assignment. Audits the Selection Judge.

  7. **SelectionSummaryJudge** — taxonomy-labeled failures -> compressed
     selection signal (root / candidate-attributable / unrecovered / terminal /
     actionable / external buckets). Real implementation wraps
     ``judge_types.reflection_judge.selection.derive_selection_summary``.

Module-level constants ``REAL`` and ``PLACEHOLDER`` enumerate implementation
status. ``PLACEHOLDER`` is empty when every cataloged judge is implemented.
"""

from __future__ import annotations

REAL = (
    "selection_judge",
    "reflection_judge",
    "mapping_judge",
    "coverage_judge",
    "quality_judge",
    "calibration_judge",
    "selection_summary_judge",
)
PLACEHOLDER: tuple[str, ...] = ()
ALL = REAL + PLACEHOLDER

__all__ = ["REAL", "PLACEHOLDER", "ALL"]
