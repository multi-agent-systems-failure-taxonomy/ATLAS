"""Claude Code runtime-skin behavior."""

from __future__ import annotations

import json
import io
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from atlas_integration.claude_code.config import ClaudeCodeConfig, parse_built_in_hooks
from atlas_integration.claude_code.hooks import (
    post_tool_use,
    post_tool_use_failure,
    session_end,
    session_start,
    stop,
    subagent_stop,
    task_completed,
)
from atlas_integration.claude_code.install import (
    REQUIRED_EVENTS,
    install,
    installed_claude_executable,
    main as install_main,
    verify_installed_hooks,
)
from atlas_integration.claude_code.uninstall import uninstall
from atlas_integration.claude_code.state import load_state
from atlas_runtime.dashboard import current_taxonomy
from atlas_runtime.evidence import EVIDENCE_FILE
from atlas_runtime.program import ProgramWorkspace
from atlas_runtime.traces import TRACE_FIELDS

ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = ROOT / "tests" / "fixtures" / "taxonomies"


def append_text(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": text}]
                    },
                }
            )
            + "\n"
        )


def append_user_text(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": text}],
                    },
                }
            )
            + "\n"
        )


def checkpoint_id(prompt: str) -> str:
    match = re.search(r"Checkpoint ID:\s*(\S+)", prompt)
    assert match
    return match.group(1)


def fired_reflection(cid: str, code: str = "MAST-12") -> str:
    return f"""ATLAS reflection:
- Checkpoint ID: {cid}
- Observe: The trace shows a verification gap.
- Map:
  - {code} | exhibited | evidence: "the full suite was not run"
- Correlate: The missing verification genuinely constitutes this failure.
- Decide: change: run the full suite before proceeding
"""


def none_reflection(cid: str) -> str:
    return f"""ATLAS reflection:
- Checkpoint ID: {cid}
- Observe: The trace is complete and verified.
- Map:
  - none apply | considered: MAST-12 | evidence: "the full suite passed"
- Correlate: No apparent match survives comparison with the evidence.
- Decide: no change needed, because verification is green
"""


class ClaudeCodeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.trace_output = self.root / "program"
        self.transcript = self.root / "main.jsonl"
        self.transcript.write_text("", encoding="utf-8")
        self.config = ClaudeCodeConfig(
            trace_output=self.trace_output,
            atlas_model="test-model",
            store_dir=STORE_DIR,
            max_retries=3,
            failure_throttle_calls=2,
            failure_recency_seconds=0,
        )
        self.base = {
            "session_id": "session-1",
            "transcript_path": str(self.transcript),
            "cwd": str(self.root),
        }
        with patch.dict(os.environ, {"ATLAS_DISABLE_DASHBOARD": "1"}):
            code, output = session_start.handle(
                {**self.base, "hook_event_name": "SessionStart"},
                self.config,
            )
        self.assertEqual(code, 0)
        self.start_output = output

    def tearDown(self):
        self.temp.cleanup()

    def test_taxonomy_is_held_at_start_and_surfaced_only_at_gate(self):
        context = self.start_output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("ATLAS runtime interaction is active", context)
        self.assertNotIn("MAST-12", context)
        state = load_state(self.trace_output, self.base["session_id"])
        self.assertEqual(state["taxonomy_id"], "mast")
        self.assertEqual(len(state["taxonomy"]["codes"]), 14)

        code, prompt = task_completed.handle(
            {
                **self.base,
                "hook_event_name": "TaskCompleted",
                "task_id": "task-1",
                "task_subject": "No-tools subtask",
            },
            self.config,
        )
        self.assertEqual(code, 2)
        self.assertIn("MAST-12", prompt)
        self.assertIn("Work the steps IN ORDER", prompt)
        self.assertIn("failure points", prompt)
        self.assertIn("`<CODE> | evidence:", prompt)
        self.assertIn("Replacement standard", prompt)
        self.assertIn("never by demonstrating an alternative's appeal", prompt)

    def test_task_completed_blocks_hollow_and_releases_valid_none_apply(self):
        event = {
            **self.base,
            "hook_event_name": "TaskCompleted",
            "task_id": "task-none",
            "task_subject": "Subtask",
        }
        code, prompt = task_completed.handle(event, self.config)
        self.assertEqual(code, 2)
        cid = checkpoint_id(prompt)
        append_text(
            self.transcript,
            f"ATLAS reflection:\n- Checkpoint ID: {cid}\n- Observe: looked",
        )
        code, error = task_completed.handle(event, self.config)
        self.assertEqual(code, 2)
        self.assertIn("ATLAS format repair", error)
        self.assertIn("empty or missing Map step", error)
        append_text(self.transcript, none_reflection(cid))
        code, _ = task_completed.handle(event, self.config)
        self.assertEqual(code, 0)

    def test_subagent_stop_blocks_then_records_fired_code(self):
        agent_transcript = self.root / "agent.jsonl"
        agent_transcript.write_text("", encoding="utf-8")
        event = {
            **self.base,
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-7",
            "agent_type": "general-purpose",
            "agent_transcript_path": str(agent_transcript),
            "stop_hook_active": False,
        }
        code, prompt = subagent_stop.handle(event, self.config)
        self.assertEqual(code, 2)
        cid = checkpoint_id(prompt)
        append_text(agent_transcript, fired_reflection(cid))
        code, _ = subagent_stop.handle(
            {**event, "stop_hook_active": True}, self.config
        )
        self.assertEqual(code, 0)
        evidence = json.loads(
            (self.trace_output / EVIDENCE_FILE).read_text(encoding="utf-8")
        )
        code_data = evidence["taxonomies"]["mast"]["codes"]["MAST-12"]
        self.assertEqual(code_data["fire_count"], 1)
        self.assertEqual(code_data["task_firings"]["agent-7"], 1)
        self.assertIn(
            "verification genuinely",
            code_data["events"][0]["correlate"],
        )

    def test_markdown_reflection_fires_code_id_with_evidence(self):
        event = {
            **self.base,
            "hook_event_name": "TaskCompleted",
            "task_id": "markdown-task",
            "task_subject": "Markdown reflection",
        }
        code, prompt = task_completed.handle(event, self.config)
        self.assertEqual(code, 2)
        cid = checkpoint_id(prompt)
        append_text(
            self.transcript,
            f"""## ATLAS Reflection
- Checkpoint ID: {cid}
**Observe:** The trace has a concrete weak point.
**Root cause:** The agent skipped verification before declaring the work done.
**Map**
- MAST-12 | evidence - "verification was absent"
**Decide**
Run the missing verification before proceeding.
""",
        )

        code, _ = task_completed.handle(event, self.config)
        self.assertEqual(code, 0)
        evidence = json.loads(
            (self.trace_output / EVIDENCE_FILE).read_text(encoding="utf-8")
        )
        code_data = evidence["taxonomies"]["mast"]["codes"]["MAST-12"]
        self.assertEqual(code_data["fire_count"], 1)
        self.assertEqual(
            code_data["events"][0]["evidence"],
            "verification was absent",
        )

    def test_wrong_checkpoint_id_is_corrected_not_rejected(self):
        # The hook owns the checkpoint id; a reflection that is valid in every
        # other respect is accepted with the id corrected instead of burning a
        # format retry on making the model echo hook-owned bookkeeping.
        event = {
            **self.base,
            "hook_event_name": "TaskCompleted",
            "task_id": "wrong-id-task",
            "task_subject": "Wrong checkpoint",
        }
        code, _prompt = task_completed.handle(event, self.config)
        self.assertEqual(code, 2)
        append_text(
            self.transcript,
            fired_reflection("not-the-pending-checkpoint"),
        )

        code, _message = task_completed.handle(event, self.config)
        self.assertEqual(code, 0)
        events = [
            json.loads(line)
            for line in (self.trace_output / "decisions.log")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        corrected = [
            entry
            for entry in events
            if entry["event"] == "checkpoint_id_corrected"
        ]
        self.assertEqual(len(corrected), 1)
        self.assertEqual(
            corrected[0]["found_checkpoint_id"],
            "not-the-pending-checkpoint",
        )

    def test_subagent_stop_rejects_hollow_and_accepts_none_apply(self):
        agent_transcript = self.root / "agent-none.jsonl"
        agent_transcript.write_text("", encoding="utf-8")
        event = {
            **self.base,
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-none",
            "agent_type": "researcher",
            "agent_transcript_path": str(agent_transcript),
            "stop_hook_active": False,
        }
        code, prompt = subagent_stop.handle(event, self.config)
        self.assertEqual(code, 2)
        cid = checkpoint_id(prompt)
        append_text(
            agent_transcript,
            f"ATLAS reflection:\n- Checkpoint ID: {cid}\n- Observe: hollow",
        )
        active = {**event, "stop_hook_active": True}
        self.assertEqual(subagent_stop.handle(active, self.config)[0], 2)
        append_text(agent_transcript, none_reflection(cid))
        self.assertEqual(subagent_stop.handle(active, self.config)[0], 0)

    def test_stop_requires_reflection_and_gate_then_guard_prevents_loop(self):
        event = {
            **self.base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Finished.",
        }
        code, prompt = stop.handle(event, self.config)
        self.assertEqual(code, 2)
        cid = checkpoint_id(prompt)
        append_text(
            self.transcript,
            f"ATLAS reflection:\n- Checkpoint ID: {cid}\n- Observe: hollow",
        )
        active = {**event, "stop_hook_active": True}
        code, _ = stop.handle(active, self.config)
        self.assertEqual(code, 2)
        # format_retries defaults to 2: the second consecutive shape failure
        # releases the gate.
        code, message = stop.handle(active, self.config)
        self.assertEqual(code, 0)
        self.assertIn("hook-owned retry limit", message)

    def test_task_completed_retry_guard_does_not_need_stop_hook_active(self):
        event = {
            **self.base,
            "hook_event_name": "TaskCompleted",
            "task_id": "bounded-task",
            "task_subject": "Malformed reflection",
        }
        _, prompt = task_completed.handle(event, self.config)
        append_text(
            self.transcript,
            "ATLAS reflection:\n"
            f"- Checkpoint ID: {checkpoint_id(prompt)}\n"
            "- Observe: still hollow",
        )
        self.assertEqual(task_completed.handle(event, self.config)[0], 2)
        code, message = task_completed.handle(event, self.config)
        self.assertEqual(code, 0)
        self.assertIn("hook-owned retry limit", message)

    def test_format_failure_gets_targeted_reprompt_and_verdict_pinning(self):
        event = {
            **self.base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Finished.",
        }
        code, prompt = stop.handle(event, self.config)
        self.assertEqual(code, 2)
        cid = checkpoint_id(prompt)
        # Valid in substance (READY verdict, no change) but missing Correlate.
        append_text(
            self.transcript,
            f"""ATLAS reflection:
- Checkpoint ID: {cid}
- Observe: The trace is complete and verified.
- Map:
  - none apply | considered: MAST-12 | evidence: "the full suite passed"
- Decide: no change needed, because verification is green
Final ATLAS status: READY_TO_SUBMIT
Codes checked: none
Evidence: the full suite passed
Repair attempts used: 0
Final decision: submit
""",
        )
        active = {**event, "stop_hook_active": True}
        code, message = stop.handle(active, self.config)
        self.assertEqual(code, 2)
        self.assertIn("ATLAS format repair", message)
        self.assertIn("empty or missing Correlate step", message)
        self.assertNotIn("empty or missing Observe step", message)
        self.assertIn("Do not re-analyze", message)
        # The re-emission is well-formed but flips the verdict; the pinned
        # pre-re-prompt status must win and the gate must release.
        append_text(
            self.transcript,
            fired_reflection(cid)
            + "\nFinal ATLAS status: REPAIR_REQUIRED\n"
            + "Repair attempts used: 0\n",
        )
        code, _message = stop.handle(active, self.config)
        self.assertEqual(code, 0)
        events = [
            json.loads(line)
            for line in (self.trace_output / "decisions.log")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        flips = [
            entry
            for entry in events
            if entry["event"] == "verdict_flip_suppressed"
        ]
        self.assertEqual(len(flips), 1)
        self.assertEqual(flips[0]["pinned_status"], "READY_TO_SUBMIT")
        self.assertEqual(flips[0]["emitted_status"], "REPAIR_REQUIRED")

    def test_shape_error_does_not_consume_repair_round(self):
        # Legacy max_retries=1 maps to repair_rounds=1 while format_retries
        # stays at its own default, so one checkpoint-id/shape slip can no
        # longer exhaust the gate before a repair is offered.
        config = ClaudeCodeConfig(
            trace_output=self.trace_output,
            atlas_model="test-model",
            store_dir=STORE_DIR,
            max_retries=1,
        )
        base = {**self.base, "session_id": "session-repair-budget"}
        with patch.dict(os.environ, {"ATLAS_DISABLE_DASHBOARD": "1"}):
            session_start.handle(
                {**base, "hook_event_name": "SessionStart"}, config
            )
        event = {
            **base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Finished.",
        }
        code, prompt = stop.handle(event, config)
        self.assertEqual(code, 2)
        cid = checkpoint_id(prompt)
        append_text(
            self.transcript,
            f"ATLAS reflection:\n- Checkpoint ID: {cid}\n- Observe: hollow",
        )
        active = {**event, "stop_hook_active": True}
        code, message = stop.handle(active, config)
        self.assertEqual(code, 2)
        self.assertIn("ATLAS format repair", message)
        append_text(
            self.transcript,
            fired_reflection(cid)
            + "\nFinal ATLAS status: REPAIR_REQUIRED\n"
            + "Repair attempts used: 0\n",
        )
        code, message = stop.handle(active, config)
        self.assertEqual(code, 2)
        self.assertIn("repair attempt 1 of 1", message)

    def test_legacy_max_retries_maps_to_repair_rounds(self):
        config = ClaudeCodeConfig(
            trace_output=self.trace_output,
            atlas_model="test-model",
            store_dir=STORE_DIR,
            max_retries=5,
        )
        self.assertEqual(config.repair_rounds, 5)
        self.assertEqual(config.format_retries, 2)
        data = config.to_dict()
        self.assertEqual(data["max_retries"], 5)
        self.assertEqual(data["repair_rounds"], 5)
        self.assertEqual(data["format_retries"], 2)

        path = self.root / "legacy-atlas.json"
        path.write_text(
            json.dumps(
                {
                    "trace_output": str(self.trace_output),
                    "atlas_model": "test-model",
                    "max_retries": 3,
                }
            ),
            encoding="utf-8",
        )
        loaded = ClaudeCodeConfig.load(path)
        self.assertEqual(loaded.repair_rounds, 3)
        self.assertEqual(loaded.format_retries, 2)

    def test_traces_are_redacted_by_default(self):
        append_text(
            self.transcript,
            "Set api_key=super-secret-token-123 before the run.",
        )
        event = {
            **self.base,
            "hook_event_name": "SessionEnd",
            "reason": "prompt_input_exit",
        }
        code, _message = session_end.handle(event, self.config)
        self.assertEqual(code, 0)
        pending = list((self.trace_output / "pending").glob("trace-*.json"))
        self.assertEqual(len(pending), 1)
        body = pending[0].read_text(encoding="utf-8")
        self.assertNotIn("super-secret-token-123", body)
        self.assertIn("[REDACTED]", body)

    def test_trace_redaction_can_be_disabled(self):
        config = ClaudeCodeConfig(
            trace_output=self.trace_output,
            atlas_model="test-model",
            store_dir=STORE_DIR,
            redact_traces=False,
        )
        base = {**self.base, "session_id": "session-noredact"}
        with patch.dict(os.environ, {"ATLAS_DISABLE_DASHBOARD": "1"}):
            session_start.handle(
                {**base, "hook_event_name": "SessionStart"}, config
            )
        append_text(self.transcript, "token check api_key=keepme-value")
        code, _message = session_end.handle(
            {**base, "hook_event_name": "SessionEnd", "reason": "exit"},
            config,
        )
        self.assertEqual(code, 0)
        pending = list((self.trace_output / "pending").glob("trace-*.json"))
        bodies = "".join(p.read_text(encoding="utf-8") for p in pending)
        self.assertIn("keepme-value", bodies)

    def test_finalize_crash_does_not_duplicate_trace(self):
        # Regression: the trace was persisted inside end_session, but
        # trace_captured was only saved after learning completed, so a crash
        # or hook-timeout kill made the retry record a second copy.
        event = {
            **self.base,
            "hook_event_name": "SessionEnd",
            "reason": "prompt_input_exit",
        }
        append_text(self.transcript, "Some session activity.")
        with patch(
            "atlas_integration.claude_code.runtime.end_session",
            side_effect=RuntimeError("learning crashed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "learning crashed"):
                session_end.handle(event, self.config)
        pending = list((self.trace_output / "pending").glob("trace-*.json"))
        self.assertEqual(len(pending), 1)
        state = load_state(self.trace_output, self.base["session_id"])
        self.assertTrue(state["trace_captured"])
        self.assertFalse(state.get("finished"))

        # The retry completes the lifecycle without re-recording the trace.
        code, _message = session_end.handle(event, self.config)
        self.assertEqual(code, 0)
        pending = list((self.trace_output / "pending").glob("trace-*.json"))
        self.assertEqual(len(pending), 1)
        state = load_state(self.trace_output, self.base["session_id"])
        self.assertTrue(state["finished"])
        self.assertEqual(state["trace_capture"]["persisted_traces"], 1)

    def test_hooks_force_background_learning(self):
        # Learning must never run inline under Claude Code's per-hook
        # timeout, regardless of the configured *_stops flags.
        config = ClaudeCodeConfig(
            trace_output=self.trace_output,
            atlas_model="test-model",
            store_dir=STORE_DIR,
            generation_stops=True,
            refinement_stops=True,
        )
        base = {**self.base, "session_id": "session-background"}
        with patch.dict(os.environ, {"ATLAS_DISABLE_DASHBOARD": "1"}):
            session_start.handle(
                {**base, "hook_event_name": "SessionStart"}, config
            )
        state = load_state(self.trace_output, base["session_id"])
        self.assertFalse(state["lifecycle"]["generation_stops"])
        self.assertFalse(state["lifecycle"]["refinement_stops"])

        captured = {}
        import atlas_integration.claude_code.runtime as rt

        real_end_session = rt.end_session

        def spy(session, **kwargs):
            captured["session"] = session
            return real_end_session(session, **kwargs)

        event = {
            **base,
            "hook_event_name": "SessionEnd",
            "reason": "prompt_input_exit",
        }
        with patch(
            "atlas_integration.claude_code.runtime.end_session",
            side_effect=spy,
        ):
            code, _message = session_end.handle(event, config)
        self.assertEqual(code, 0)
        self.assertFalse(captured["session"].generation_stops)
        self.assertFalse(captured["session"].refinement_stops)

    def test_three_completed_repairs_each_receive_fresh_re_evaluation(self):
        event = {
            **self.base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Finished.",
        }
        _, prompt = stop.handle(event, self.config)
        append_text(
            self.transcript,
            fired_reflection(checkpoint_id(prompt))
            + "\nFinal ATLAS status: REPAIR_REQUIRED\n"
            + "Repair attempts used: 0\n",
        )
        active = {**event, "stop_hook_active": True}
        code, message = stop.handle(active, self.config)
        self.assertEqual(code, 2)
        self.assertIn("repair attempt 1 of 3", message)
        started = [
            json.loads(line)
            for line in (self.trace_output / "decisions.log")
            .read_text(encoding="utf-8")
            .splitlines()
            if json.loads(line)["event"] == "repair_round_started"
        ]
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["repair_round"], 1)
        self.assertIn("change:", started[0]["decide"])

        for completed in range(1, 4):
            append_text(
                self.transcript,
                f"Repair {completed} completed and verified.",
            )
            code, recheck_prompt = stop.handle(active, self.config)
            self.assertEqual(code, 2)
            self.assertIn("post-repair submission re-evaluation", recheck_prompt)
            self.assertIn(
                f"Repair {completed} completed and verified.",
                recheck_prompt,
            )
            self.assertIn(
                f"`Repair attempts used: {completed}`",
                recheck_prompt,
            )
            append_text(
                self.transcript,
                fired_reflection(checkpoint_id(recheck_prompt))
                + "\nFinal ATLAS status: REPAIR_REQUIRED\n"
                + f"Repair attempts used: {completed}\n",
            )
            code, message = stop.handle(active, self.config)
            if completed < 3:
                self.assertEqual(code, 2)
                self.assertIn(
                    f"repair attempt {completed + 1} of 3",
                    message,
                )

        self.assertEqual(code, 0)
        self.assertIn("hook-owned retry limit", message)
        evidence = json.loads(
            (self.trace_output / EVIDENCE_FILE).read_text(encoding="utf-8")
        )
        self.assertEqual(
            evidence["taxonomies"]["mast"]["codes"]["MAST-12"]["fire_count"],
            4,
        )

    def test_reported_repair_count_mismatch_does_not_block(self):
        event = {
            **self.base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Finished.",
        }
        _, prompt = stop.handle(event, self.config)
        append_text(
            self.transcript,
            none_reflection(checkpoint_id(prompt))
            + "\nFinal ATLAS status: READY_TO_SUBMIT\n"
            + "Repair attempts used: 1\n",
        )
        code, message = stop.handle(
            {**event, "stop_hook_active": True},
            self.config,
        )
        self.assertEqual(code, 0)
        self.assertIn("accepted", message)

    def test_change_decision_cannot_claim_ready_to_submit(self):
        event = {
            **self.base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Finished.",
        }
        _, prompt = stop.handle(event, self.config)
        append_text(
            self.transcript,
            fired_reflection(checkpoint_id(prompt))
            + "\nFinal ATLAS status: READY_TO_SUBMIT\n"
            + "Codes checked: MAST-12\n"
            + "Evidence: verification is missing\n"
            + "Repair attempts used: 0\n"
            + "Final decision: submit\n",
        )
        code, message = stop.handle(
            {**event, "stop_hook_active": True},
            self.config,
        )
        self.assertEqual(code, 2)
        self.assertIn("must be REPAIR_REQUIRED", message)
        self.assertIn("still provisional", message)

    def test_full_stop_prompt_marks_answer_provisional(self):
        event = {
            **self.base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Finished.",
        }
        _, prompt = stop.handle(event, self.config)
        self.assertIn("earlier task answer is PROVISIONAL", prompt)
        self.assertIn("Never say the answer was already submitted", prompt)
        self.assertIn("READY_TO_SUBMIT or REPAIR_REQUIRED", prompt)

    def test_stop_valid_reflection_and_final_gate_release(self):
        event = {
            **self.base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Finished.",
        }
        code, prompt = stop.handle(event, self.config)
        self.assertEqual(code, 2)
        cid = checkpoint_id(prompt)
        append_text(
            self.transcript,
            none_reflection(cid)
            + "\nFinal ATLAS status: READY_TO_SUBMIT\n"
            + "Codes checked: MAST-12\n"
            + "Evidence: full suite passed\n"
            + "Repair attempts used: 0\n"
            + "Final decision: submit\n",
        )
        code, _ = stop.handle(
            {**event, "stop_hook_active": True}, self.config
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            ProgramWorkspace(self.trace_output).load()["active_sessions"],
            [],
        )

    def test_prompt_requested_major_segment_uses_light_stop_checkpoint(self):
        event = {
            **self.base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": (
                "ATLAS checkpoint request: investigation is complete"
            ),
        }
        code, prompt = stop.handle(event, self.config)
        self.assertEqual(code, 2)
        self.assertIn("voluntary major-segment checkpoint", prompt)
        self.assertNotIn("Final ATLAS status:", prompt)
        append_text(self.transcript, none_reflection(checkpoint_id(prompt)))
        code, message = stop.handle(
            {**event, "stop_hook_active": True}, self.config
        )
        self.assertEqual(code, 2)
        self.assertIn("Continue the task", message)

    def test_blocked_final_gate_does_not_double_count_on_retry(self):
        event = {
            **self.base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Finished.",
        }
        _, prompt = stop.handle(event, self.config)
        cid = checkpoint_id(prompt)
        append_text(
            self.transcript,
            fired_reflection(cid)
            + "\nFinal ATLAS status: REPAIR_REQUIRED\n"
            + "Repair attempts used: 0\n",
        )
        active = {**event, "stop_hook_active": True}
        self.assertEqual(stop.handle(active, self.config)[0], 2)
        append_text(self.transcript, "Repair 1 completed and verified.")
        code, recheck_prompt = stop.handle(active, self.config)
        self.assertEqual(code, 2)
        append_text(
            self.transcript,
            none_reflection(checkpoint_id(recheck_prompt))
            + "\nFinal ATLAS status: READY_TO_SUBMIT\n"
            + "Repair attempts used: 1\n",
        )
        self.assertEqual(stop.handle(active, self.config)[0], 0)
        evidence = json.loads(
            (self.trace_output / EVIDENCE_FILE).read_text(encoding="utf-8")
        )
        self.assertEqual(
            evidence["taxonomies"]["mast"]["codes"]["MAST-12"]["fire_count"],
            1,
        )

    def test_post_tool_filters_and_throttles_both_failure_sources(self):
        success = {
            **self.base,
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_response": {"stdout": "12 tests passed", "exitCode": 0},
        }
        self.assertEqual(post_tool_use.handle(success, self.config), (0, None))

        failed_test = {
            **success,
            "tool_response": {
                "stdout": "FAILED test_x - AssertionError",
                "exitCode": 0,
            },
        }
        code, output = post_tool_use.handle(failed_test, self.config)
        self.assertEqual(code, 0)
        self.assertIn(
            "MAST-12",
            output["hookSpecificOutput"]["additionalContext"],
        )
        self.assertEqual(post_tool_use.handle(failed_test, self.config), (0, None))

        actual = {
            **self.base,
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "Bash",
            "error": "process failed with exit code 2",
        }
        code, output = post_tool_use_failure.handle(actual, self.config)
        self.assertEqual(code, 0)
        self.assertIsNotNone(output)

    def test_fired_code_appears_live_in_dashboard_with_evidence(self):
        event = {
            **self.base,
            "hook_event_name": "TaskCompleted",
            "task_id": "task-live",
            "task_subject": "Dashboard evidence",
        }
        _, prompt = task_completed.handle(event, self.config)
        cid = checkpoint_id(prompt)
        append_text(self.transcript, fired_reflection(cid))
        code, _ = task_completed.handle(event, self.config)
        self.assertEqual(code, 0)

        data = current_taxonomy(
            ProgramWorkspace(self.trace_output), STORE_DIR
        )
        item = next(
            code for code in data["codes"] if code["code_id"] == "MAST-12"
        )
        self.assertEqual(item["fire_count"], 1)
        self.assertEqual(
            item["task_firings"],
            [
                {
                    "task_id": "task-live",
                    "label": "task-liv",
                    "count": 1,
                }
            ],
        )
        runtime = item["runtime_evidence"]
        self.assertEqual(runtime[0]["evidence"], "the full suite was not run")
        self.assertIn("verification genuinely", runtime[0]["correlate"])

    def test_zero_tool_path_can_process_task_completed_and_stop(self):
        task = {
            **self.base,
            "hook_event_name": "TaskCompleted",
            "task_id": "zero-tools",
            "task_subject": "Explicit task with no tools",
        }
        _, prompt = task_completed.handle(task, self.config)
        append_text(self.transcript, none_reflection(checkpoint_id(prompt)))
        self.assertEqual(task_completed.handle(task, self.config)[0], 0)

        stop_event = {
            **self.base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Done.",
        }
        _, prompt = stop.handle(stop_event, self.config)
        append_text(
            self.transcript,
            none_reflection(checkpoint_id(prompt))
            + "\nFinal ATLAS status: READY_TO_SUBMIT\n"
            + "Repair attempts used: 0\n",
        )
        self.assertEqual(
            stop.handle(
                {**stop_event, "stop_hook_active": True}, self.config
            )[0],
            0,
        )

    def test_successful_stop_records_one_canonical_generation_trace(self):
        append_user_text(self.transcript, "Implement the Claude adapter.")
        append_text(self.transcript, "Implemented and verified.")
        event = {
            **self.base,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Done.",
        }
        _, prompt = stop.handle(event, self.config)
        append_text(
            self.transcript,
            none_reflection(checkpoint_id(prompt))
            + "\nFinal ATLAS status: READY_TO_SUBMIT\n"
            + "Codes checked: MAST-12\n"
            + "Evidence: tests passed\n"
            + "Repair attempts used: 0\n"
            + "Final decision: submit\n",
        )
        self.assertEqual(
            stop.handle({**event, "stop_hook_active": True}, self.config)[0],
            0,
        )
        traces = list(ProgramWorkspace(self.trace_output).pending.iter_traces())
        self.assertEqual(len(traces), 1)
        trace = traces[0]
        self.assertEqual(tuple(trace.to_dict()), TRACE_FIELDS)
        self.assertEqual(trace.task, "Implement the Claude adapter.")
        self.assertIn("Implemented and verified.", trace.raw_trajectory)
        self.assertIn('"type": "assistant"', trace.raw_trajectory)
        self.assertEqual(trace.metadata["harness"], "claude_code")
        state = load_state(self.trace_output, self.base["session_id"])
        self.assertTrue(state["trace_captured"])
        self.assertEqual(state["trace_capture"]["persisted_traces"], 1)

    def test_successive_completed_turns_become_distinct_episode_traces(self):
        def complete_turn(task: str, answer: str) -> None:
            append_user_text(self.transcript, task)
            append_text(self.transcript, answer)
            event = {
                **self.base,
                "hook_event_name": "Stop",
                "stop_hook_active": False,
                "last_assistant_message": answer,
            }
            code, prompt = stop.handle(event, self.config)
            self.assertEqual(code, 2)
            append_text(
                self.transcript,
                none_reflection(checkpoint_id(prompt))
                + "\nFinal ATLAS status: READY_TO_SUBMIT\n"
                + "Codes checked: none\n"
                + "Evidence: targeted verification passed\n"
                + "Repair attempts used: 0\n"
                + "Final decision: submit\n",
            )
            self.assertEqual(
                stop.handle(
                    {**event, "stop_hook_active": True},
                    self.config,
                )[0],
                0,
            )

        complete_turn("FIRST CLAUDE TASK MARKER", "FIRST CLAUDE ANSWER MARKER")
        complete_turn("SECOND CLAUDE TASK MARKER", "SECOND CLAUDE ANSWER MARKER")
        duplicate = stop.handle(
            {
                **self.base,
                "hook_event_name": "Stop",
                "stop_hook_active": False,
                "last_assistant_message": "SECOND CLAUDE ANSWER MARKER",
            },
            self.config,
        )
        self.assertEqual(duplicate, (0, "ATLAS episode already committed."))

        traces = sorted(
            ProgramWorkspace(self.trace_output).pending.iter_traces(),
            key=lambda trace: trace.metadata["episode_sequence"],
        )
        self.assertEqual(len(traces), 2)
        self.assertEqual(
            [trace.metadata["episode_sequence"] for trace in traces],
            [1, 2],
        )
        self.assertEqual(traces[0].task, "FIRST CLAUDE TASK MARKER")
        self.assertEqual(traces[1].task, "SECOND CLAUDE TASK MARKER")
        self.assertIn("FIRST CLAUDE ANSWER MARKER", traces[0].raw_trajectory)
        self.assertNotIn("FIRST CLAUDE ANSWER MARKER", traces[1].raw_trajectory)
        self.assertIn("SECOND CLAUDE ANSWER MARKER", traces[1].raw_trajectory)
        state = load_state(self.trace_output, self.base["session_id"])
        self.assertEqual(state["episode_sequence"], 2)
        self.assertEqual(state["conversation_taxonomy_root"], "mast")

    def test_five_completed_episodes_queue_exactly_one_native_generation_job(self):
        config = replace(
            self.config,
            learning_backend="claude_subagent",
            generation_threshold=5,
            claude_cli_path=Path(sys.executable),
        )
        workspace = ProgramWorkspace(self.trace_output)
        with workspace.locked_manifest() as manifest:
            manifest["generation"]["retry_after_count"] = 5

        with (
            patch(
                "atlas_integration.claude_code.runtime.enqueue_claude_learning_job",
                return_value="claude-generation-five",
            ) as enqueue,
            patch(
                "atlas_runtime.generation._atlas_generate",
                side_effect=AssertionError("provider generation must not run"),
            ) as provider,
        ):
            for index in range(1, 6):
                task = f"CLAUDE TASK {index}"
                answer = f"CLAUDE ANSWER {index}"
                append_user_text(self.transcript, task)
                append_text(self.transcript, answer)
                event = {
                    **self.base,
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                    "last_assistant_message": answer,
                }
                code, prompt = stop.handle(event, config)
                self.assertEqual(code, 2)
                append_text(
                    self.transcript,
                    none_reflection(checkpoint_id(prompt))
                    + "\nFinal ATLAS status: READY_TO_SUBMIT\n"
                    + "Codes checked: none\n"
                    + "Evidence: targeted verification passed\n"
                    + "Repair attempts used: 0\n"
                    + "Final decision: submit\n",
                )
                self.assertEqual(
                    stop.handle(
                        {**event, "stop_hook_active": True},
                        config,
                    )[0],
                    0,
                )

        self.assertEqual(enqueue.call_count, 1)
        self.assertEqual(enqueue.call_args.kwargs["kind"], "generation")
        provider.assert_not_called()
        self.assertEqual(len(list(workspace.pending.iter_traces())), 5)

    def test_session_end_captures_once_when_stop_did_not_finish(self):
        append_user_text(self.transcript, "Investigate an interrupted task.")
        append_text(self.transcript, "Partial work before interruption.")
        event = {
            **self.base,
            "hook_event_name": "SessionEnd",
            "reason": "other",
        }
        self.assertEqual(session_end.handle(event, self.config)[0], 0)
        self.assertEqual(session_end.handle(event, self.config), (0, None))
        workspace = ProgramWorkspace(self.trace_output)
        self.assertEqual(workspace.pending.count(), 1)
        self.assertEqual(workspace.load()["active_sessions"], [])


class ClaudeCodeInstallerTests(unittest.TestCase):
    def test_config_round_trip_preserves_runtime_environment_and_trace_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "config.json"
            config = ClaudeCodeConfig(
                trace_output=root / "program",
                atlas_model="gpt-5",
                store_dir=root / "store",
                trace_root=root / "learning-traces",
                dashboard=False,
                openai_base_url="http://127.0.0.1:8742/v1",
                openai_api_key_env="ATLAS_PROXY_KEY",
                generation_threshold=7,
                generation_stops=True,
                skip_judge=True,
                k_init=11,
                k=21,
                refinement_stops=True,
                advanced_refinement=True,
            )
            path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
            loaded = ClaudeCodeConfig.load(path)
            self.assertEqual(loaded.trace_root, (root / "learning-traces").resolve())
            self.assertFalse(loaded.dashboard)
            self.assertEqual(
                loaded.openai_base_url,
                "http://127.0.0.1:8742/v1",
            )
            self.assertEqual(loaded.openai_api_key_env, "ATLAS_PROXY_KEY")
            self.assertEqual(loaded.generation_threshold, 7)
            self.assertTrue(loaded.generation_stops)
            self.assertTrue(loaded.skip_judge)
            self.assertEqual(loaded.k_init, 11)
            self.assertEqual(loaded.k, 21)
            self.assertTrue(loaded.refinement_stops)
            self.assertTrue(loaded.advanced_refinement)
            self.assertNotIn(
                "local-proxy",
                path.read_text(encoding="utf-8"),
            )

    def test_plaintext_credential_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "trace_output": str(Path(td) / "program"),
                        "atlas_model": "gpt-5",
                        "openai_api_key": "secret-value",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "plaintext"):
                ClaudeCodeConfig.load(path)

    def test_executable_discovery_prefers_explicit_override_then_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            explicit = root / "explicit-claude"
            from_path = root / "path-claude"
            explicit.write_bytes(b"explicit")
            from_path.write_bytes(b"path")
            with (
                patch.dict(
                    os.environ,
                    {"CLAUDE_CODE_EXECUTABLE": str(explicit)},
                    clear=False,
                ),
                patch(
                    "atlas_integration.claude_code.install.shutil.which",
                    return_value=str(from_path),
                ),
            ):
                self.assertEqual(installed_claude_executable(), explicit.resolve())
            with (
                patch.dict(
                    os.environ,
                    {"CLAUDE_CODE_EXECUTABLE": ""},
                    clear=False,
                ),
                patch(
                    "atlas_integration.claude_code.install.shutil.which",
                    return_value=str(from_path),
                ),
            ):
                self.assertEqual(installed_claude_executable(), from_path.resolve())

    def test_session_start_uses_configured_lifecycle_controls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            transcript = root / "trace.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = ClaudeCodeConfig(
                trace_output=root / "program",
                atlas_model="gpt-5",
                store_dir=STORE_DIR,
                dashboard=False,
                generation_threshold=7,
                generation_stops=True,
                skip_judge=True,
                k_init=11,
                k=21,
                refinement_stops=True,
                advanced_refinement=True,
            )
            code, _ = session_start.handle(
                {
                    "hook_event_name": "SessionStart",
                    "session_id": "configured",
                    "transcript_path": str(transcript),
                    "cwd": str(root),
                },
                config,
            )
            self.assertEqual(code, 0)
            state = load_state(root / "program", "configured")
            self.assertEqual(state["lifecycle"]["generation_threshold"], 7)
            self.assertTrue(state["lifecycle"]["skip_judge"])
            self.assertEqual(state["lifecycle"]["k_init"], 11)
            self.assertEqual(state["lifecycle"]["k"], 21)
            self.assertTrue(state["lifecycle"]["advanced_refinement"])
            # The *_stops flags are deliberately NOT honored on hook paths:
            # learning must run in background workers, never inline under
            # Claude Code's per-hook timeout.
            self.assertFalse(state["lifecycle"]["generation_stops"])
            self.assertFalse(state["lifecycle"]["refinement_stops"])

    def test_hook_contract_verifier_accepts_supported_version(self):
        with tempfile.TemporaryDirectory() as td:
            executable = Path(td) / "claude"
            executable.write_bytes(
                b"\n".join(
                    [event.encode() for event in REQUIRED_EVENTS]
                    + [
                        b"prevent task completion",
                        b"show stderr to subagent and continue having it run",
                        b"show stderr to model and continue conversation",
                        b"hookSpecificOutput.additionalContext",
                    ]
                )
            )
            completed = unittest.mock.Mock(stdout="2.1.185 (Claude Code)\n")
            with patch(
                "atlas_integration.claude_code.install.subprocess.run",
                return_value=completed,
            ):
                version = verify_installed_hooks(executable)

        self.assertRegex(version, r"\d+\.\d+\.\d+")

    def test_installer_registers_all_events_without_duplication(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = ClaudeCodeConfig(
                trace_output=root / "program",
                atlas_model="test-model",
                store_dir=STORE_DIR,
            )
            first = install(root, config, verify=False)
            install(root, config, verify=False)
            settings = json.loads(
                Path(first["settings"]).read_text(encoding="utf-8")
            )
            self.assertEqual(set(settings["hooks"]), set(REQUIRED_EVENTS))
            for event in REQUIRED_EVENTS:
                self.assertEqual(len(settings["hooks"][event]), 1)
                command = settings["hooks"][event][0]["hooks"][0]["command"]
                # Module invocation, never a dispatcher file path: the path
                # goes stale when the install mode or location changes, and
                # then every hook event fails.
                self.assertIn(
                    "-m atlas_integration.claude_code.dispatcher",
                    command,
                )
                self.assertNotIn("dispatcher.py", command)
                if os.name == "nt":
                    self.assertNotIn("\\", command)

    def test_installer_can_filter_built_in_hooks_and_tool_matchers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = ClaudeCodeConfig(
                trace_output=root / "program",
                atlas_model="test-model",
                store_dir=STORE_DIR,
                built_in_hooks=parse_built_in_hooks({
                    "SubagentStop": False,
                    "PostToolUse": ["Bash", "Edit"],
                    "PostToolUseFailure": ["Bash"],
                }),
            )
            result = install(root, config, verify=False)
            settings = json.loads(
                Path(result["settings"]).read_text(encoding="utf-8")
            )

            self.assertNotIn("SubagentStop", settings["hooks"])
            self.assertNotIn("SubagentStop", result["events"])
            self.assertEqual(
                {entry["matcher"] for entry in settings["hooks"]["PostToolUse"]},
                {"Bash", "Edit"},
            )
            self.assertEqual(
                [entry["matcher"] for entry in settings["hooks"]["PostToolUseFailure"]],
                ["Bash"],
            )
            for event in {"SessionStart", "SessionEnd", "Stop", "TaskCompleted"}:
                self.assertIn(event, settings["hooks"])
                self.assertNotIn("matcher", settings["hooks"][event][0])

    def test_installer_refuses_invalid_existing_settings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            claude = root / ".claude"
            claude.mkdir()
            settings = claude / "settings.local.json"
            settings.write_text("{broken", encoding="utf-8")
            config = ClaudeCodeConfig(
                trace_output=root / "program",
                atlas_model="test-model",
                store_dir=STORE_DIR,
            )
            with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
                install(root, config, verify=False)
            self.assertEqual(settings.read_text(encoding="utf-8"), "{broken")
            self.assertFalse((claude / "atlas-skill.json").exists())

    def test_verification_failure_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = ClaudeCodeConfig(
                trace_output=root / "program",
                atlas_model="test-model",
                store_dir=STORE_DIR,
            )
            with (
                patch(
                    "atlas_integration.claude_code.install.verify_installed_hooks",
                    side_effect=RuntimeError("missing hook"),
                ),
                self.assertRaisesRegex(RuntimeError, "missing hook"),
            ):
                install(root, config)
            self.assertFalse((root / ".claude").exists())

    def test_user_level_install_is_zero_config_and_native_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with (
                patch(
                    "atlas_integration.claude_code.install.Path.home",
                    return_value=root,
                ),
                patch(
                    "atlas_integration.claude_code.install.verify_installed_hooks",
                    return_value="9.9.9",
                ),
                redirect_stdout(io.StringIO()) as output,
                redirect_stderr(io.StringIO()),
            ):
                code = install_main(["--user-level"])

            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["scope"], "user")
            config = ClaudeCodeConfig.load(
                root / ".claude" / "atlas-skill.json"
            )
            self.assertEqual(
                config.trace_output.resolve(),
                (root / ".atlas-skill" / "interactive").resolve(),
            )
            self.assertEqual(config.atlas_model, "interactive-session")
            self.assertEqual(config.project_scope, "auto")
            self.assertEqual(config.session_selector, "prompt")
            self.assertEqual(config.selector_surface, "browser")
            self.assertEqual(config.learning_backend, "claude_subagent")
            self.assertIsNone(config.openai_api_key_env)

    def test_user_level_install_rejects_project_target(self):
        with self.assertRaises(SystemExit):
            install_main(["--user-level", "--project-dir", "."])

    def test_empty_inherit_form_resolves_picker_at_install_time(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            captured = {}

            def fake_install(_project, config, **_kwargs):
                captured["inherit"] = config.inherit
                return {}

            with (
                patch(
                    "atlas_integration.claude_code.install.resolver.resolve",
                    return_value="tax-django-orm-001",
                ) as resolve,
                patch(
                    "atlas_integration.claude_code.install.install",
                    side_effect=fake_install,
                ),
            ):
                self.assertEqual(
                    install_main(
                        [
                            "--project-dir",
                            str(root),
                            "--trace-output",
                            str(root / "program"),
                            "--atlas-model",
                            "gpt-5",
                            "--store-dir",
                            str(STORE_DIR),
                            "--inherit",
                        ]
                    ),
                    0,
                )
            self.assertEqual(captured["inherit"], "tax-django-orm-001")
            self.assertEqual(resolve.call_count, 1)

    def test_inherit_pick_resolves_picker_at_install_time(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            captured = {}

            def fake_install(_project, config, **_kwargs):
                captured["inherit"] = config.inherit
                return {}

            with (
                patch(
                    "atlas_integration.claude_code.install.resolver.resolve",
                    return_value="tax-django-orm-001",
                ) as resolve,
                patch(
                    "atlas_integration.claude_code.install.install",
                    side_effect=fake_install,
                ),
            ):
                self.assertEqual(
                    install_main(
                        [
                            "--project-dir",
                            str(root),
                            "--trace-output",
                            str(root / "program"),
                            "--atlas-model",
                            "gpt-5",
                            "--store-dir",
                            str(STORE_DIR),
                            "--inherit-pick",
                        ]
                    ),
                    0,
                )
            self.assertEqual(captured["inherit"], "tax-django-orm-001")
            self.assertEqual(resolve.call_count, 1)

    def test_uninstall_removes_only_atlas_registration_and_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = ClaudeCodeConfig(
                trace_output=root / "program",
                atlas_model="test-model",
                store_dir=STORE_DIR,
            )
            info = install(root, config, verify=False)
            settings_path = Path(info["settings"])
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            settings["hooks"]["Stop"].append(
                {
                    "hooks": [
                        {"type": "command", "command": "other-tool stop"}
                    ]
                }
            )
            settings_path.write_text(
                json.dumps(settings),
                encoding="utf-8",
            )

            result = uninstall(root)

            self.assertTrue(result["config_removed"])
            remaining = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(
                remaining["hooks"]["Stop"],
                [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "other-tool stop",
                            }
                        ]
                    }
                ],
            )
            self.assertNotIn("SessionStart", remaining["hooks"])

    def test_uninstall_preserves_atlas_named_unrelated_hook(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = ClaudeCodeConfig(
                trace_output=root / "program",
                atlas_model="test-model",
                store_dir=STORE_DIR,
            )
            info = install(root, config, verify=False)
            settings_path = Path(info["settings"])
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            settings["hooks"]["Stop"].append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "my-atlas-failure-modes-notifier stop",
                        }
                    ]
                }
            )
            settings_path.write_text(json.dumps(settings), encoding="utf-8")

            uninstall(root)

            remaining = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertIn(
                "my-atlas-failure-modes-notifier",
                json.dumps(remaining),
            )


if __name__ == "__main__":
    unittest.main()
