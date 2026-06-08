"""Smoke (B): T1 swap path.

Two scenarios:
  - Healthy traces: induction passes the quality floor, SKILL.md flips from
    MAST to the induced taxonomy.
  - Thin/junk traces: quality floor rejects, SKILL.md stays on the MAST floor,
    runtime exposes a "low-confidence, using MAST" reason.

We mock atlas.generate_taxonomy so the test is hermetic (no LLM call, no API
key). The runtime + render + accumulator code paths are exercised end-to-end.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from claude_code_skill import runtime
from claude_code_skill.accumulator import Trace, get_accumulator


def _trace(i: int) -> Trace:
    return Trace(
        task_id=f"task-{i:03d}",
        transcript=[{"role": "assistant", "content": f"working on task {i}"}],
        tool_calls=[],
        final_gate_status="READY_TO_SUBMIT",
        repair_attempts_used=0,
        evidence=f"tests passed for {i}",
        outcome="submitted",
    )


HEALTHY_RAW_TAXONOMY = {
    "metadata": {"traces_analyzed": 5, "counts": {"category_a": 4, "category_b": 4, "category_c": 4, "total": 12}},
    "category_definitions": {"A": "System failures", "B": "Role failures", "C": "Domain failures"},
    "annotation_layer": {
        "category_a": [
            {"code": f"A.{i}", "name": f"A failure {i}",
             "definition": f"specific concrete A failure {i}",
             "severity": "major"} for i in range(1, 5)
        ],
        "category_b": [
            {"code": f"B.{i}", "name": f"Solver failure {i}",
             "definition": f"specific concrete B failure {i}",
             "severity": "major",
             "applies_to_role": "solver"} for i in range(1, 5)
        ],
        "category_c": [
            {"code": f"C.{i}", "name": f"Domain failure {i}",
             "definition": f"specific concrete C failure {i}",
             "severity": "major"} for i in range(1, 5)
        ],
    },
    "full_layer": {
        "category_a": [{"code": f"A.{i}", "support": 3} for i in range(1, 5)],
        "category_b": [{"code": f"B.{i}", "support": 3} for i in range(1, 5)],
        "category_c": [{"code": f"C.{i}", "support": 3} for i in range(1, 5)],
    },
}

THIN_RAW_TAXONOMY = {
    "metadata": {"traces_analyzed": 5, "counts": {"category_a": 2, "category_b": 1, "category_c": 1, "total": 4}},
    "category_definitions": {},
    "annotation_layer": {
        "category_a": [
            {"code": "A.1", "name": "fail", "definition": "x", "severity": "major"},
            {"code": "A.2", "name": "fail", "definition": "y", "severity": "minor"},
        ],
        "category_b": [
            {"code": "B.1", "name": "solver fail", "definition": "z",
             "severity": "major", "applies_to_role": "solver"},
        ],
        "category_c": [
            {"code": "C.1", "name": "domain fail", "definition": "w", "severity": "minor"},
        ],
    },
    "full_layer": {
        # All singleton (support=1) so the floor culls everything
        "category_a": [{"code": "A.1", "support": 1}, {"code": "A.2", "support": 1}],
        "category_b": [{"code": "B.1", "support": 1}],
        "category_c": [{"code": "C.1", "support": 1}],
    },
}


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path):
    runtime.reset_state()
    yield
    runtime.reset_state()


def test_healthy_t1_promotes(tmp_path):
    """5 healthy traces (threshold = 5) → induction passes → SKILL.md flips."""
    target = tmp_path / "SKILL.md"
    runtime.ensure_floor_rendered(target)
    assert "MAST failure-mode checklist" in target.read_text(encoding="utf-8")

    acc = get_accumulator()
    for i in range(5):
        acc.add_trace(_trace(i))

    with patch("claude_code_skill.induction.generate_taxonomy",
               return_value=HEALTHY_RAW_TAXONOMY):
        reason = runtime.tick(target)

    assert "promoted" in reason
    body = target.read_text(encoding="utf-8")
    assert "ATLAS failure-mode taxonomy" in body
    assert "MAST failure-mode checklist" not in body
    # Stable IDs visible in the rendered body
    assert "A.1" in body and "B.1" in body and "C.1" in body


def test_thin_seed_stays_on_mast(tmp_path):
    """Thin/singleton taxonomy → quality floor rejects → SKILL.md stays MAST."""
    target = tmp_path / "SKILL.md"
    runtime.ensure_floor_rendered(target)
    mast_body = target.read_text(encoding="utf-8")

    acc = get_accumulator()
    for i in range(5):
        acc.add_trace(_trace(i))

    with patch("claude_code_skill.induction.generate_taxonomy",
               return_value=THIN_RAW_TAXONOMY):
        reason = runtime.tick(target)

    assert "low-confidence" in reason.lower() or "quality floor failed" in reason
    # SKILL.md must NOT have been flipped
    assert target.read_text(encoding="utf-8") == mast_body


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
