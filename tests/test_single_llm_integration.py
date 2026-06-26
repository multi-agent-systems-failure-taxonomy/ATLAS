"""Single-model, no-harness runtime integration."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from atlas_integration.single_llm import SingleLLMConfig, run_single_llm
from atlas_runtime.evidence import EVIDENCE_FILE
from atlas_runtime.program import ProgramWorkspace

ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = ROOT / "tests" / "fixtures" / "taxonomies"


def checkpoint_id(messages) -> str:
    match = re.search(r"Checkpoint ID:\s*(\S+)", messages[-1]["content"])
    assert match
    return match.group(1)


def clean_reflection(messages, *, status=None, attempts=0) -> str:
    cid = checkpoint_id(messages)
    tail = ""
    if status:
        tail = f"""
Final ATLAS status: {status}
Codes checked: MAST-12
Evidence: The scoped work was verified.
Repair attempts used: {attempts}
Final decision: {"submit" if status == "READY_TO_SUBMIT" else "repair"}
"""
    return f"""ATLAS reflection:
- Checkpoint ID: {cid}
- Observe: The scoped execution is concrete and verified.
- Map:
  - none apply | considered: MAST-12 | evidence: "verification is present"
- Correlate: The verification gap does not occur in this segment.
- Decide: no change needed, because the relevant work was verified.
{tail}"""


class SingleLLMIntegrationTests(unittest.TestCase):
    def test_checkpoint_then_final_gate_records_trace_and_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task_calls = 0

            def call(messages):
                nonlocal task_calls
                prompt = messages[-1]["content"]
                if "reflection required" in prompt:
                    return clean_reflection(
                        messages,
                        status=(
                            "READY_TO_SUBMIT"
                            if "final submission gate" in prompt
                            else None
                        ),
                    )
                task_calls += 1
                if task_calls == 1:
                    return (
                        "I completed the data extraction.\n"
                        "ATLAS checkpoint request: extraction complete"
                    )
                return "The final answer is 42."

            result = run_single_llm(
                "Solve the task.",
                call,
                SingleLLMConfig(
                    trace_output=root / "program",
                    atlas_model="gpt-5",
                    store_dir=STORE_DIR,
                    trace_root=root / "traces",
                    dashboard=False,
                ),
                problem_id="single-task",
            )

            self.assertEqual(result.answer, "The final answer is 42.")
            self.assertEqual(result.checkpoint_count, 1)
            self.assertEqual(result.session_end.persisted_traces, 1)
            self.assertEqual(
                ProgramWorkspace(root / "program").pending.count(),
                1,
            )
            evidence = json.loads(
                (root / "program" / EVIDENCE_FILE).read_text(encoding="utf-8")
            )
            self.assertEqual(len(evidence["checkpoints"]), 2)

    def test_repair_required_causes_one_more_agent_turn(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            answers = 0
            final_gates = 0

            def call(messages):
                nonlocal answers, final_gates
                prompt = messages[-1]["content"]
                if "final submission gate" in prompt:
                    final_gates += 1
                    cid = checkpoint_id(messages)
                    if final_gates == 1:
                        return f"""ATLAS reflection:
- Checkpoint ID: {cid}
- Observe: The answer lacks verification.
- Map:
  - MAST-12 | exhibited | evidence: "no verification was shown"
- Correlate: This is a real verification failure.
- Decide: change: verify the calculation

Final ATLAS status: REPAIR_REQUIRED
Codes checked: MAST-12
Evidence: No verification was shown.
Repair attempts used: 0
Final decision: repair
"""
                    return clean_reflection(
                        messages,
                        status="READY_TO_SUBMIT",
                        attempts=1,
                    )
                answers += 1
                return (
                    "Unverified answer: 41."
                    if answers == 1
                    else "Verified corrected answer: 42."
                )

            result = run_single_llm(
                "Calculate the answer.",
                call,
                SingleLLMConfig(
                    trace_output=root / "program",
                    atlas_model="gpt-5",
                    store_dir=STORE_DIR,
                    trace_root=root / "traces",
                    dashboard=False,
                ),
            )
            self.assertEqual(result.answer, "Verified corrected answer: 42.")
            self.assertEqual(answers, 2)
            self.assertEqual(final_gates, 2)


if __name__ == "__main__":
    unittest.main()
