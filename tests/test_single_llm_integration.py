"""Single-model, no-harness runtime integration."""

from __future__ import annotations

import json
import re
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from atlas_integration.single_llm import SingleLLMConfig, run_single_llm
from atlas_integration.single_llm.cli import provider_call
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
    def test_learning_cadence_flows_from_config(self):
        # Regression: SingleLLMConfig silently ignored the documented
        # generation_threshold / k_init / k fields, so atlas.json learning
        # cadence never reached the session.
        import atlas_integration.single_llm.runtime as rt

        captured = {}
        real_start_session = rt.start_session

        def spy(*args, **kwargs):
            captured.update(kwargs)
            return real_start_session(*args, **kwargs)

        def call(messages):
            prompt = messages[-1]["content"]
            if "reflection required" in prompt:
                return clean_reflection(messages, status="READY_TO_SUBMIT")
            return "The answer is 42."

        with tempfile.TemporaryDirectory() as td, patch.object(
            rt, "start_session", side_effect=spy
        ):
            root = Path(td)
            run_single_llm(
                "Solve the task.",
                call,
                SingleLLMConfig(
                    trace_output=root / "program",
                    atlas_model="gpt-5",
                    store_dir=STORE_DIR,
                    trace_root=root / "traces",
                    dashboard=False,
                    generation_threshold=3,
                    k_init=4,
                    k=6,
                    freeze=True,
                ),
            )
        self.assertEqual(captured["generation_threshold"], 3)
        self.assertEqual(captured["k_init"], 4)
        self.assertEqual(captured["k"], 6)

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

    def test_format_failure_reprompts_targeted_and_pins_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            format_repairs = 0

            def call(messages):
                nonlocal format_repairs
                prompt = messages[-1]["content"]
                if "ATLAS format repair" in prompt:
                    format_repairs += 1
                    cid = checkpoint_id(messages)
                    # Well-formed re-emission that flips the verdict.
                    return f"""ATLAS reflection:
- Checkpoint ID: {cid}
- Observe: A second look claims a gap.
- Map:
  - MAST-12 | evidence: "second-guessed verification"
- Correlate: Re-prompt pressure produced a new story.
- Decide: change: rewrite the answer

Final ATLAS status: REPAIR_REQUIRED
Codes checked: MAST-12
Evidence: second-guessed verification
Repair attempts used: 0
Final decision: repair
"""
                if "final submission gate" in prompt:
                    cid = checkpoint_id(messages)
                    # Missing Correlate -> form failure; verdict is READY.
                    return f"""ATLAS reflection:
- Checkpoint ID: {cid}
- Observe: The answer was verified end to end.
- Map:
  - none apply | considered: MAST-12 | evidence: "verification passed"
- Decide: no change needed, because verification passed

Final ATLAS status: READY_TO_SUBMIT
Codes checked: none
Evidence: verification passed
Repair attempts used: 0
Final decision: submit
"""
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
                problem_id="pinned-task",
            )
            # One targeted re-prompt; the flipped verdict is pinned to the
            # pre-re-prompt READY status, so no repair round runs.
            self.assertEqual(format_repairs, 1)
            self.assertEqual(result.answer, "The final answer is 42.")
            self.assertTrue(result.gate_allowed)

    def test_release_policy_returns_best_answer_after_gate_cap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            final_gates = 0

            def call(messages):
                nonlocal final_gates
                prompt = messages[-1]["content"]
                if "final submission gate" in prompt:
                    final_gates += 1
                    cid = checkpoint_id(messages)
                    return f"""ATLAS reflection:
- Checkpoint ID: {cid}
- Observe: The answer still lacks verification.
- Map:
  - MAST-12 | evidence: "verification was not shown"
- Correlate: The model is guessing.
- Decide: change: verify before release

Final ATLAS status: REPAIR_REQUIRED
Codes checked: MAST-12
Evidence: Verification was not shown.
Repair attempts used: 0
Final decision: repair
"""
                return "Best available answer."

            result = run_single_llm(
                "Calculate the answer.",
                call,
                SingleLLMConfig(
                    trace_output=root / "program",
                    atlas_model="gpt-5",
                    store_dir=STORE_DIR,
                    trace_root=root / "traces",
                    dashboard=False,
                    max_retries=1,
                    gate_exhaustion_policy="release",
                ),
            )
            self.assertEqual(result.answer, "Best available answer.")
            self.assertFalse(result.gate_allowed)
            self.assertEqual(final_gates, 2)

    def test_recent_activity_window_bounds_final_gate_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seen_prompt = {}

            def call(messages):
                prompt = messages[-1]["content"]
                if "final submission gate" in prompt:
                    seen_prompt["text"] = prompt
                    return clean_reflection(messages, status="READY_TO_SUBMIT")
                return "x" * 2000

            run_single_llm(
                "Important task prompt.",
                call,
                SingleLLMConfig(
                    trace_output=root / "program",
                    atlas_model="gpt-5",
                    store_dir=STORE_DIR,
                    trace_root=root / "traces",
                    dashboard=False,
                    recent_activity_messages=1,
                    recent_activity_chars=500,
                ),
            )
            prompt = seen_prompt["text"]
            self.assertIn("Important task prompt", prompt)
            self.assertLess(len(prompt), 8000)

    def test_cli_provider_call_uses_boto3_for_bedrock_model(self):
        captured = {}

        class Client:
            def converse(self, **kwargs):
                captured.update(kwargs)
                return {
                    "output": {
                        "message": {
                            "content": [{"text": "bedrock answer"}],
                        }
                    }
                }

        fake_boto3 = SimpleNamespace(
            client=lambda service, region_name=None: captured.update(
                {"service": service, "region_name": region_name}
            ) or Client()
        )
        with patch.dict(
            os.environ,
            {
                "AWS_BEARER_TOKEN_BEDROCK": "token",
                "AWS_REGION": "us-east-1",
                "OPENAI_BASE_URL": "",
            },
            clear=False,
        ):
            with patch.dict(sys.modules, {"boto3": fake_boto3}):
                call = provider_call(
                    "us.anthropic.claude-haiku-4-5-20251001-v1:0"
                )
                result = call(
                    [
                        {"role": "system", "content": "system"},
                        {"role": "user", "content": "hello"},
                    ]
                )

        self.assertEqual(result, "bedrock answer")
        self.assertEqual(captured["service"], "bedrock-runtime")
        self.assertEqual(captured["region_name"], "us-east-1")
        self.assertEqual(captured["system"][0]["text"], "system")
        self.assertEqual(captured["messages"][0]["content"][0]["text"], "hello")


if __name__ == "__main__":
    unittest.main()
