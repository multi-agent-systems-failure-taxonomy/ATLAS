"""Codex hook integration behavior."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from atlas_integration.codex.config import CodexConfig, parse_codex_hooks
from atlas_integration.codex.dispatcher import _merge_notices
from atlas_integration.codex.install import SKILL_NAME, install, install_skill
from atlas_integration.codex.runtime import (
    session_start,
    stop,
    subagent_stop,
    user_prompt_submit,
)
from atlas_integration.codex.state import load_state
from atlas_integration.codex.transcript import (
    first_user_message,
    read_raw_transcript,
)
from atlas_integration.codex.uninstall import uninstall, uninstall_skill
from atlas_runtime.evidence import EVIDENCE_FILE
from atlas_runtime.program import ProgramWorkspace

ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = ROOT / "tests" / "fixtures" / "taxonomies"


def append_text(path: Path, text: str, *, role: str = "assistant") -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": role,
                    "message": {
                        "role": role,
                        "content": [{"type": "text", "text": text}],
                    },
                }
            )
            + "\n"
        )


def append_item(path: Path, item: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item) + "\n")


def checkpoint_id(prompt: str) -> str:
    match = re.search(r"Checkpoint ID:\s*(\S+)", prompt)
    assert match
    return match.group(1)


def passing_report(prompt: str) -> str:
    cid = checkpoint_id(prompt)
    return f"""ATLAS reflection:
- Checkpoint ID: {cid}
- Observe: The requested turn was completed and checked.
- Correlate: No evidence-supported failure remains.
- Map:
  - none apply | considered: MAST-12 | evidence: "checked"
- Decide: no change needed, because verification passed.

Final ATLAS status: READY_TO_SUBMIT
Codes checked: none
Evidence: targeted verification passed
Repair attempts used: 0
Final decision: submit
"""


def compact_report(
    checkpoint: str = "task complete",
    *,
    codes: str = "none apply",
    evidence: str = "targeted verification passed",
    next_action: str = "complete",
) -> str:
    return f"""Checkpoint: {checkpoint}
Relevant codes: {codes}
Evidence: {evidence}
Next action: {next_action}
"""


class CodexIntegrationTests(unittest.TestCase):
    def base_config(self, root: Path) -> CodexConfig:
        return CodexConfig(
            trace_output=root / "program",
            atlas_model="test-model",
            store_dir=STORE_DIR,
            dashboard=False,
        )

    def selector_config(
        self,
        root: Path,
        *,
        store_dir: Path | None = None,
    ) -> CodexConfig:
        return replace(
            self.base_config(root),
            store_dir=store_dir or STORE_DIR,
            session_selector="prompt",
        )

    def test_default_hooks_can_be_customized(self):
        specs = parse_codex_hooks(
            {
                "SubagentStop": False,
                "PostToolUse": {"matchers": ["Bash", "Edit|Write"]},
            }
        )
        by_event = {spec.event: spec for spec in specs}
        self.assertTrue(by_event["UserPromptSubmit"].enabled)
        self.assertFalse(by_event["SubagentStop"].enabled)
        self.assertEqual(by_event["PostToolUse"].matchers, ("Bash", "Edit|Write"))

    def test_learning_notice_merges_with_existing_gate_message(self):
        output = _merge_notices(
            {"continue": True, "systemMessage": "ATLAS reflection accepted."},
            ["ATLAS taxonomy generation triggered"],
        )
        self.assertTrue(output["continue"])
        self.assertEqual(
            output["systemMessage"],
            "ATLAS reflection accepted.\n\nATLAS taxonomy generation triggered",
        )

    def test_auto_project_scope_derives_program_from_event_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "atlas-home"
            first = root / "first-project"
            second = root / "second-project"
            first.mkdir()
            second.mkdir()
            config = CodexConfig(
                trace_output=base,
                atlas_model="test-model",
                store_dir=STORE_DIR,
                dashboard=False,
                project_scope="auto",
                task_group="default",
            )
            first_config = config.for_event({"cwd": str(first)})
            second_config = config.for_event({"cwd": str(second)})
            self.assertNotEqual(
                first_config.trace_output,
                second_config.trace_output,
            )
            self.assertEqual(config.trace_output, base)
            self.assertIn("projects", first_config.trace_output.parts)
            self.assertEqual(first_config.trace_output.name, "program")

    def test_project_scope_round_trips_through_saved_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "atlas.json"
            config = CodexConfig(
                trace_output=root / "atlas-home",
                atlas_model="test-model",
                store_dir=STORE_DIR,
                dashboard=False,
                project_scope="auto",
                project_id="company-tools",
                task_group="platform",
            )
            path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
            loaded = CodexConfig.load(path)
            self.assertEqual(loaded.project_scope, "auto")
            self.assertEqual(loaded.project_id, "company-tools")
            self.assertEqual(loaded.task_group, "platform")

    def test_session_selector_round_trips_through_saved_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "atlas.json"
            config = replace(
                self.base_config(root),
                session_selector="prompt",
            )
            path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
            loaded = CodexConfig.load(path)
            self.assertEqual(loaded.session_selector, "prompt")

    def test_native_learning_backend_round_trips_without_api_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "atlas.json"
            config = replace(
                self.base_config(root),
                learning_backend="codex_subagent",
                worker_model="gpt-test",
                codex_cli_path=root / "codex.exe",
                worker_timeout_seconds=321,
            )
            path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
            loaded = CodexConfig.load(path)
            self.assertEqual(loaded.learning_backend, "codex_subagent")
            self.assertEqual(loaded.worker_model, "gpt-test")
            self.assertEqual(loaded.codex_cli_path, (root / "codex.exe").resolve())
            self.assertEqual(loaded.worker_timeout_seconds, 321)
            self.assertIsNone(loaded.openai_api_key_env)

    def test_native_learning_rejects_blocking_provider_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, "requires background"):
                replace(
                    self.base_config(root),
                    learning_backend="codex_subagent",
                    generation_stops=True,
                )

    def test_install_writes_project_hooks_and_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = install(root, self.base_config(root), python=Path("python"))
            hooks_path = Path(result["hooks"])
            config_path = Path(result["config"])
            self.assertTrue(hooks_path.exists())
            self.assertTrue(config_path.exists())
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]
            self.assertIn("SessionStart", hooks)
            self.assertIn("UserPromptSubmit", hooks)
            self.assertIn("Stop", hooks)
            text = json.dumps(hooks)
            self.assertIn("atlas_integration.codex.dispatcher", text)

    def test_uninstall_removes_only_atlas_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            install(root, self.base_config(root), python=Path("python"))
            hooks_path = root / ".codex" / "hooks.json"
            data = json.loads(hooks_path.read_text(encoding="utf-8"))
            data["hooks"].setdefault("Stop", []).append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python other.py",
                        }
                    ]
                }
            )
            hooks_path.write_text(json.dumps(data), encoding="utf-8")
            result = uninstall(root)
            self.assertGreater(result["removed_hooks"], 0)
            cleaned = json.loads(hooks_path.read_text(encoding="utf-8"))
            self.assertIn("other.py", json.dumps(cleaned))
            self.assertFalse((root / ".codex" / "atlas-skill.json").exists())

    def test_stop_hook_commits_compact_checkpoint_in_one_callback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = self.base_config(root)
            event = {
                "hook_event_name": "SessionStart",
                "session_id": "codex-session",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }
            start = session_start(event, config)
            self.assertIn(
                "ATLAS runtime interaction is active",
                start["hookSpecificOutput"]["additionalContext"],
            )
            append_text(transcript, "Compute 2 + 2.", role="user")
            final_report = (
                "2 + 2 = 4. I am ready to submit.\n\n"
                + compact_report(
                    "arithmetic verified",
                    evidence="2 + 2 = 4",
                )
            )
            append_text(transcript, final_report)
            accepted = stop(
                {**event, "hook_event_name": "Stop"},
                config,
            )
            self.assertTrue(accepted["continue"])
            self.assertNotIn("decision", accepted)
            self.assertIn("checkpoint accepted", accepted["systemMessage"])
            state = load_state(config.trace_output, "codex-session")
            self.assertTrue(state["trace_captured"])
            self.assertEqual(state["gate_result"]["status"], "READY_TO_SUBMIT")
            evidence = json.loads(
                (config.trace_output / EVIDENCE_FILE).read_text(encoding="utf-8")
            )
            self.assertEqual(len(evidence["checkpoints"]), 1)
            self.assertEqual(state["taxonomy_id"], "mast")

    def test_successive_completed_turns_become_distinct_episode_traces(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = self.base_config(root)
            event = {
                "session_id": "multi-turn",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }
            session_start({**event, "hook_event_name": "SessionStart"}, config)

            def complete_turn(task: str, answer: str) -> None:
                append_text(transcript, task, role="user")
                report = answer + "\n\n" + compact_report(task)
                append_text(transcript, report)
                accepted = stop(
                    {
                        **event,
                        "hook_event_name": "Stop",
                        "last_assistant_message": report,
                    },
                    config,
                )
                self.assertTrue(accepted["continue"])

            complete_turn("FIRST TASK MARKER", "FIRST ANSWER MARKER")
            complete_turn("SECOND TASK MARKER", "SECOND ANSWER MARKER")
            duplicate = stop({**event, "hook_event_name": "Stop"}, config)
            self.assertTrue(duplicate["continue"])
            self.assertIn("already committed", duplicate["systemMessage"])

            traces = sorted(
                ProgramWorkspace(config.trace_output).pending.iter_traces(),
                key=lambda trace: trace.metadata["episode_sequence"],
            )
            self.assertEqual(len(traces), 2)
            self.assertEqual(
                [trace.metadata["episode_sequence"] for trace in traces],
                [1, 2],
            )
            self.assertEqual(traces[0].task, "FIRST TASK MARKER")
            self.assertEqual(traces[1].task, "SECOND TASK MARKER")
            self.assertIn("FIRST ANSWER MARKER", traces[0].raw_trajectory)
            self.assertNotIn("FIRST ANSWER MARKER", traces[1].raw_trajectory)
            self.assertIn("SECOND ANSWER MARKER", traces[1].raw_trajectory)
            state = load_state(config.trace_output, "multi-turn")
            self.assertEqual(state["episode_sequence"], 2)
            self.assertEqual(state["conversation_taxonomy_root"], "mast")

    def test_missing_compact_checkpoint_warns_but_never_strands_episode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = self.base_config(root)
            event = {
                "session_id": "missing-checkpoint",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }
            session_start({**event, "hook_event_name": "SessionStart"}, config)
            append_text(transcript, "Complete the task.", role="user")
            append_text(transcript, "The task is complete and verified.")

            result = stop({**event, "hook_event_name": "Stop"}, config)

            self.assertTrue(result["continue"])
            self.assertIn("missing or invalid", result["systemMessage"])
            state = load_state(config.trace_output, event["session_id"])
            self.assertTrue(state["finished"])
            self.assertTrue(state["trace_captured"])
            self.assertEqual(
                state["gate_result"]["status"],
                "MISSING_CHECKPOINT",
            )

    def test_subagent_stop_is_observational_and_never_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = self.base_config(root)
            event = {
                "session_id": "subagent-observational",
                "cwd": str(root),
                "transcript_path": str(transcript),
                "agent_id": "worker-1",
                "agent_type": "worker",
            }
            session_start({**event, "hook_event_name": "SessionStart"}, config)

            plain = subagent_stop(
                {
                    **event,
                    "hook_event_name": "SubagentStop",
                    "last_assistant_message": "Worker finished without a checkpoint.",
                },
                config,
            )
            self.assertIsNone(plain)

            checkpoint = compact_report("worker pass complete")
            captured = subagent_stop(
                {
                    **event,
                    "hook_event_name": "SubagentStop",
                    "last_assistant_message": checkpoint,
                },
                config,
            )
            self.assertTrue(captured["continue"])
            self.assertNotIn("decision", captured)

    def test_next_user_prompt_recovers_skipped_stop_without_merging_tasks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = self.base_config(root)
            event = {
                "session_id": "recover-next-prompt",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }
            session_start({**event, "hook_event_name": "SessionStart"}, config)
            append_text(transcript, "FIRST RECOVERY TASK", role="user")
            user_prompt_submit(
                {
                    **event,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "FIRST RECOVERY TASK",
                },
                config,
            )
            append_text(transcript, "FIRST RECOVERY ANSWER")

            append_text(transcript, "SECOND RECOVERY TASK", role="user")
            recovered = user_prompt_submit(
                {
                    **event,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "SECOND RECOVERY TASK",
                },
                config,
            )

            self.assertIn("recovered", recovered["systemMessage"].lower())
            traces = list(ProgramWorkspace(config.trace_output).pending.iter_traces())
            self.assertEqual(len(traces), 1)
            self.assertEqual(traces[0].task, "FIRST RECOVERY TASK")
            self.assertIn("FIRST RECOVERY ANSWER", traces[0].raw_trajectory)
            self.assertNotIn("SECOND RECOVERY TASK", traces[0].raw_trajectory)
            state = load_state(config.trace_output, event["session_id"])
            self.assertFalse(state["finished"])
            self.assertEqual(state["episode_sequence"], 2)
            self.assertEqual(state["episode_task"], "SECOND RECOVERY TASK")

    def test_codex_transcript_normalizer_excludes_harness_context(self):
        with tempfile.TemporaryDirectory() as temp:
            transcript = Path(temp) / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            append_item(
                transcript,
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "developer",
                        "content": [{"type": "input_text", "text": "SECRET SYSTEM"}],
                    },
                },
            )
            append_item(
                transcript,
                {
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "call_id": "skill-read",
                        "name": "exec",
                        "input": (
                            "Get-Content C:\\Users\\tester\\.codex\\skills\\"
                            "browser\\SKILL.md"
                        ),
                    },
                },
            )
            append_item(
                transcript,
                {
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "call_id": "skill-read",
                        "output": "Control the in-app Browser. PRIVATE SKILL TEXT",
                    },
                },
            )
            append_item(
                transcript,
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "REAL HUMAN TASK",
                    },
                },
            )
            append_item(
                transcript,
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "REAL HUMAN TASK"}],
                    },
                },
            )
            append_item(
                transcript,
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "<hook_prompt>ATLAS PRIVATE TAXONOMY</hook_prompt>",
                            }
                        ],
                    },
                },
            )
            append_item(
                transcript,
                {
                    "type": "event_msg",
                    "payload": {"type": "agent_reasoning", "text": "PRIVATE REASONING"},
                },
            )
            append_item(
                transcript,
                {
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "call_id": "call-1",
                        "name": "exec",
                        "input": '{"command":"pytest"}',
                    },
                },
            )
            append_item(
                transcript,
                {
                    "type": "event_msg",
                    "payload": {"type": "agent_message", "message": "VISIBLE ANSWER"},
                },
            )

            normalized = read_raw_transcript(transcript)

            self.assertEqual(first_user_message(transcript), "REAL HUMAN TASK")
            self.assertEqual(normalized.count("REAL HUMAN TASK"), 1)
            self.assertIn("VISIBLE ANSWER", normalized)
            self.assertIn("pytest", normalized)
            self.assertNotIn("SECRET SYSTEM", normalized)
            self.assertNotIn("ATLAS PRIVATE TAXONOMY", normalized)
            self.assertNotIn("PRIVATE REASONING", normalized)
            self.assertNotIn("PRIVATE SKILL TEXT", normalized)

    def test_external_tool_workdir_surfaces_project_scope_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bound = root / "bound"
            external = root / "external"
            bound.mkdir()
            external.mkdir()
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = self.base_config(root)
            event = {
                "session_id": "scope-warning",
                "cwd": str(bound),
                "transcript_path": str(transcript),
            }
            session_start({**event, "hook_event_name": "SessionStart"}, config)
            append_text(transcript, "Work on the bound project.", role="user")
            append_item(
                transcript,
                {
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "call_id": "scope-call",
                        "name": "exec",
                        "input": (
                            'tools.shell_command({command:"git status",'
                            f'"workdir":"{str(external).replace(chr(92), chr(92) * 2)}"'
                            "})"
                        ),
                    },
                },
            )
            report = "Done.\n\n" + compact_report("scope task complete")
            append_text(transcript, report)

            result = stop(
                {**event, "hook_event_name": "Stop", "last_assistant_message": report},
                config,
            )

            self.assertIn("project scope mismatch", result["systemMessage"].lower())
            trace = next(ProgramWorkspace(config.trace_output).pending.iter_traces())
            self.assertEqual(trace.metadata["external_workdirs"], [str(external.resolve())])

    def test_five_completed_episodes_queue_exactly_one_generation_job(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = replace(
                self.base_config(root),
                learning_backend="codex_subagent",
                generation_threshold=5,
                codex_cli_path=Path(sys.executable),
            )
            event = {
                "session_id": "five-episode-generation",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }
            session_start({**event, "hook_event_name": "SessionStart"}, config)
            workspace = ProgramWorkspace(config.trace_output)
            with workspace.locked_manifest() as manifest:
                manifest["generation"]["retry_after_count"] = 5

            with (
                patch(
                    "atlas_integration.codex.runtime.enqueue_learning_job",
                    return_value="codex-generation-five",
                ) as enqueue,
                patch(
                    "atlas_runtime.generation._atlas_generate",
                    side_effect=AssertionError("provider generation must not run"),
                ) as provider,
            ):
                for index in range(1, 6):
                    append_text(transcript, f"TASK {index}", role="user")
                    report = (
                        f"ANSWER {index}\n\n"
                        + compact_report(f"task {index} complete")
                    )
                    append_text(transcript, report)
                    result = stop(
                        {
                            **event,
                            "hook_event_name": "Stop",
                            "last_assistant_message": report,
                        },
                        config,
                    )
                    self.assertTrue(result["continue"])

            self.assertEqual(enqueue.call_count, 1)
            self.assertEqual(enqueue.call_args.kwargs["kind"], "generation")
            provider.assert_not_called()
            traces = list(workspace.pending.iter_traces())
            self.assertEqual(len(traces), 5)

    def test_native_backend_queues_codex_worker_without_provider_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = replace(
                self.base_config(root),
                learning_backend="codex_subagent",
                generation_threshold=1,
                codex_cli_path=Path(sys.executable),
            )
            event = {
                "session_id": "native-learning",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }
            session_start({**event, "hook_event_name": "SessionStart"}, config)
            workspace = ProgramWorkspace(config.trace_output)
            with workspace.locked_manifest() as manifest:
                manifest["generation"]["retry_after_count"] = 1
            append_text(transcript, "Build the demo.", role="user")
            report = (
                "The demo is built and verified.\n\n"
                + compact_report("demo built")
            )
            append_text(transcript, report)
            with (
                patch(
                    "atlas_integration.codex.runtime.enqueue_learning_job",
                    return_value="codex-generation-test",
                ) as enqueue,
                patch(
                    "atlas_runtime.generation._atlas_generate",
                    side_effect=AssertionError("provider generation must not run"),
                ) as provider,
            ):
                accepted = stop(
                    {
                        **event,
                        "hook_event_name": "Stop",
                        "last_assistant_message": report,
                    },
                    config,
            )
            self.assertTrue(accepted["continue"])
            native_state = load_state(config.trace_output, "native-learning")
            self.assertEqual(
                enqueue.call_count,
                1,
                msg=f"trace capture: {native_state.get('trace_capture')}",
            )
            self.assertEqual(enqueue.call_args.kwargs["kind"], "generation")
            provider.assert_not_called()

    def test_selector_holds_first_task_then_resumes_with_mast(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            empty_store = root / "taxonomies"
            empty_store.mkdir()
            config = self.selector_config(root, store_dir=empty_store)
            event = {
                "session_id": "selector-mast",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }

            started = session_start(
                {**event, "hook_event_name": "SessionStart"}, config
            )
            context = started["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Which taxonomy should ATLAS use", context)
            self.assertIn("1. MAST  [Recommended]", context)
            self.assertIn("2. No taxonomy", context)

            append_text(transcript, "ORIGINAL TASK MARKER", role="user")
            held = user_prompt_submit(
                {
                    **event,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "ORIGINAL TASK MARKER",
                },
                config,
            )
            self.assertIn(
                "Do not perform or analyze",
                held["hookSpecificOutput"]["additionalContext"],
            )
            append_text(transcript, "ATLAS SELECTOR MARKER")
            waiting = stop({**event, "hook_event_name": "Stop"}, config)
            self.assertTrue(waiting["continue"])
            self.assertIn("waiting for taxonomy", waiting["systemMessage"])

            append_text(transcript, "1", role="user")
            accepted_choice = user_prompt_submit(
                {
                    **event,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "1",
                },
                config,
            )
            self.assertIn("Continue it now", json.dumps(accepted_choice))
            state = load_state(config.trace_output, "selector-mast")
            self.assertEqual(state["selection"]["status"], "selected")
            self.assertEqual(state["taxonomy_id"], "mast")
            self.assertEqual(state["episode_task"], "ORIGINAL TASK MARKER")

            append_text(transcript, "ORIGINAL TASK ANSWER MARKER")
            report = (
                "ORIGINAL TASK ANSWER MARKER\n\n"
                + compact_report("original task complete")
            )
            append_text(transcript, report)
            final = stop(
                {
                    **event,
                    "hook_event_name": "Stop",
                    "last_assistant_message": report,
                },
                config,
            )
            self.assertTrue(final["continue"])

            traces = list(ProgramWorkspace(config.trace_output).pending.iter_traces())
            self.assertEqual(len(traces), 1)
            self.assertEqual(traces[0].task, "ORIGINAL TASK MARKER")
            self.assertIn("ORIGINAL TASK ANSWER MARKER", traces[0].raw_trajectory)
            self.assertNotIn("ATLAS SELECTOR MARKER", traces[0].raw_trajectory)

    def test_no_taxonomy_disables_gates_and_trace_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            empty_store = root / "taxonomies"
            empty_store.mkdir()
            config = self.selector_config(root, store_dir=empty_store)
            event = {
                "session_id": "selector-disabled",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }
            session_start({**event, "hook_event_name": "SessionStart"}, config)
            append_text(transcript, "DISABLED TASK", role="user")
            user_prompt_submit(
                {
                    **event,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "DISABLED TASK",
                },
                config,
            )
            append_text(transcript, "No taxonomy", role="user")
            selected = user_prompt_submit(
                {
                    **event,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "No taxonomy",
                },
                config,
            )
            self.assertIn("ATLAS disabled", selected["systemMessage"])
            self.assertIsNone(stop({**event, "hook_event_name": "Stop"}, config))
            state = load_state(config.trace_output, "selector-disabled")
            self.assertEqual(state["selection"]["status"], "disabled")
            workspace = ProgramWorkspace(config.trace_output)
            self.assertEqual(workspace.load()["active_sessions"], [])
            self.assertEqual(list(workspace.pending.iter_traces()), [])

    def test_stored_taxonomy_becomes_project_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = self.selector_config(root)
            first = {
                "session_id": "selector-taxonomy-first",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }
            session_start({**first, "hook_event_name": "SessionStart"}, config)
            chosen = user_prompt_submit(
                {
                    **first,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "tax-django-orm-001",
                },
                config,
            )
            self.assertIn("tax-django-orm-001", json.dumps(chosen))
            user_prompt_submit(
                {
                    **first,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Inspect the ORM.",
                },
                config,
            )
            state = load_state(config.trace_output, first["session_id"])
            self.assertEqual(state["taxonomy_id"], "tax-django-orm-001")
            self.assertEqual(
                ProgramWorkspace(config.trace_output).load()["taxonomy_id"],
                "tax-django-orm-001",
            )

            second = {
                **first,
                "session_id": "selector-taxonomy-second",
            }
            next_start = session_start(
                {**second, "hook_event_name": "SessionStart"}, config
            )
            context = next_start["hookSpecificOutput"]["additionalContext"]
            self.assertIn("tax-django-orm-001  [Recommended]", context)
            self.assertNotIn("tax-flask-routing-004", context)
            self.assertNotIn("1. MAST", context)

    def test_optional_skill_install_uninstall_still_works(self):
        with tempfile.TemporaryDirectory() as temp:
            skills_dir = Path(temp) / "skills"
            result = install_skill(skills_dir=skills_dir)
            self.assertEqual(result.skill_dir, skills_dir / SKILL_NAME)
            self.assertTrue(result.skill_md.exists())
            summary = uninstall_skill(skills_dir=skills_dir)
            self.assertIn(str(result.skill_md), summary["removed"])
            self.assertFalse(result.skill_md.exists())

    def test_skill_uninstall_refuses_unmarked_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            skills_dir = Path(temp) / "skills"
            skill_dir = skills_dir / SKILL_NAME
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("user skill", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                uninstall_skill(skills_dir=skills_dir)


if __name__ == "__main__":
    unittest.main()
