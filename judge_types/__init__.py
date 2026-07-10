"""ATLAS skill judge types.

The simple LLM judges are natural-language assets under ``judge_types/assets``
run by ``JudgeController``. Reflection remains a deeper orchestrated judge, and
selection-summary remains deterministic Python.
"""

from __future__ import annotations

from .simple import (
    CalibrationJudge,
    CalibrationJudgeResult,
    CoverageJudge,
    CoverageJudgeResult,
    JudgeController,
    MappingJudge,
    MappingJudgeResult,
    QualityJudge,
    QualityJudgeResult,
    SelectionJudge,
    SelectionJudgeResult,
    SIMPLE_JUDGE_TYPES,
    load_judge_definition,
    render_judge_prompt,
    run_calibration,
    run_coverage,
    run_mapping,
    run_quality,
    run_selection,
)

REAL = (
    "selection",
    "reflection_judge",
    "mapping",
    "coverage",
    "quality",
    "calibration",
    "selection_summary_judge",
)
PLACEHOLDER: tuple[str, ...] = ()
ALL = REAL + PLACEHOLDER

__all__ = [
    "REAL",
    "PLACEHOLDER",
    "ALL",
    "SIMPLE_JUDGE_TYPES",
    "JudgeController",
    "load_judge_definition",
    "render_judge_prompt",
    "SelectionJudge",
    "SelectionJudgeResult",
    "MappingJudge",
    "MappingJudgeResult",
    "CoverageJudge",
    "CoverageJudgeResult",
    "QualityJudge",
    "QualityJudgeResult",
    "CalibrationJudge",
    "CalibrationJudgeResult",
    "run_selection",
    "run_mapping",
    "run_coverage",
    "run_quality",
    "run_calibration",
]
