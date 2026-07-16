"""Codex hook integration behavior."""

from __future__ import annotations

import json
import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from atlas_integration.codex.config import CodexConfig, parse_codex_hooks
from atlas_integration.codex.browser_picker import apply_browser_choice
from atlas_integration.codex.dispatcher import (
    _is_internal_codex_event,
    _merge_learning_context,
    _merge_notices,
    main as dispatcher_main,
)
from atlas_integration.codex.install import (
    SKILL_NAME,
    install,
    install_skill,
    main as install_main,
)
from atlas_integration.codex.runtime import (
    _next_action_requires_repair,
    session_start,
    stop,
    subagent_stop,
    user_prompt_submit,
)
from atlas_integration.codex.state import load_state, save_state
from atlas_integration.codex.transcript import (
    first_user_message,
    read_raw_transcript,
)
from atlas_integration.codex.uninstall import uninstall, uninstall_skill
from atlas_runtime.evidence import EVIDENCE_FILE
from atlas_runtime.program import ProgramWorkspace
from atlas_runtime.traces import GenerationTrace

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
    def test_compact_next_action_negation_is_ready(self):
        self.assertFalse(
            _next_action_requires_repair("no further action required")
        )
        self.assertFalse(_next_action_requires_repair("no repair required"))
        self.assertTrue(_next_action_requires_repair("repair required"))
        self.assertTrue(_next_action_requires_repair("report unresolved"))

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
            selector_surface="inline",
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

    def test_learning_dispatch_preserves_existing_hook_context(self):
        output = _merge_learning_context(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": "Existing ATLAS standing context.",
                }
            },
            "Launch the native taxonomy subagent.",
        )

        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "UserPromptSubmit")
        self.assertEqual(
            specific["additionalContext"],
            "Existing ATLAS standing context.\n\n"
            "Launch the native taxonomy subagent.",
        )
        self.assertTrue(output["continue"])

    def test_dispatcher_ignores_codex_internal_memory_tasks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / ".codex"
            memories = codex_home / "memories"
            memories.mkdir(parents=True)
            config = self.base_config(root)
            config_path = root / "atlas-skill.json"
            config_path.write_text(
                json.dumps(config.to_dict()),
                encoding="utf-8",
            )
            event = {
                "hook_event_name": "SessionStart",
                "session_id": "internal-memory-task",
                "cwd": str(memories),
            }
            stdout = io.StringIO()

            with (
                patch.dict("os.environ", {"CODEX_HOME": str(codex_home)}),
                patch("sys.stdin", io.StringIO(json.dumps(event))),
                redirect_stdout(stdout),
            ):
                code = dispatcher_main(["--config", str(config_path)])
                self.assertTrue(_is_internal_codex_event(event))
                self.assertFalse(
                    _is_internal_codex_event(
                        {**event, "cwd": str(root / "project")}
                    )
                )

            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertFalse(config.trace_output.exists())

    def test_dispatcher_does_not_claim_learning_before_browser_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = replace(
                self.selector_config(root),
                selector_surface="browser",
                learning_backend="codex_subagent",
            )
            config_path = root / "atlas-skill.json"
            config_path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
            event = {
                "hook_event_name": "SessionStart",
                "session_id": "internal-child-session",
                "cwd": str(root),
                "source": "startup",
            }
            stdout = io.StringIO()

            with (
                patch("sys.stdin", io.StringIO(json.dumps(event))),
                redirect_stdout(stdout),
                patch("atlas_integration.codex.dispatcher.poll_learning_jobs") as poll,
                patch("atlas_integration.codex.dispatcher.claim_learning_job") as claim,
            ):
                code = dispatcher_main(["--config", str(config_path)])

            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(
                load_state(config.trace_output, event["session_id"]),
                {},
            )
            poll.assert_not_called()
            claim.assert_not_called()

    def test_dispatcher_polls_and_claims_missed_generation_on_user_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = replace(
                self.base_config(root),
                learning_backend="codex_subagent",
                generation_threshold=5,
            )
            config_path = root / "atlas-skill.json"
            config_path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
            workspace = ProgramWorkspace(config.trace_output, repo="demo")
            workspace.pending.append_many_with_names(
                GenerationTrace(
                    problem_id=f"episode-{index}",
                    task=f"Task {index}",
                    raw_trajectory=f"Completed trace {index}",
                )
                for index in range(5)
            )
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            event = {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "poll-session",
                "cwd": str(root),
                "transcript_path": str(transcript),
                "prompt": "Continue the main task.",
            }
            stdout = io.StringIO()
            with patch("sys.stdin", io.StringIO(json.dumps(event))), redirect_stdout(
                stdout
            ):
                code = dispatcher_main(["--config", str(config_path)])

            self.assertEqual(code, 0)
            output = json.loads(stdout.getvalue())
            context = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("ATLAS native taxonomy learning is ready", context)
            self.assertIn("SUBAGENT TASK BEGIN", context)
            job_path = next(
                (config.trace_output / "learning_jobs").glob("*/job.json")
            )
            self.assertEqual(
                json.loads(job_path.read_text(encoding="utf-8"))["state"],
                "claimed",
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
                selector_surface="inline",
            )
            path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
            loaded = CodexConfig.load(path)
            self.assertEqual(loaded.session_selector, "prompt")
            self.assertEqual(loaded.selector_surface, "inline")

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

    def test_user_level_install_is_zero_config_and_native_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                patch(
                    "atlas_integration.codex.install.Path.home",
                    return_value=root,
                ),
                redirect_stdout(io.StringIO()) as output,
            ):
                code = install_main(["--user-level"])

            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["scope"], "user")
            config = CodexConfig.load(root / ".codex" / "atlas-skill.json")
            self.assertEqual(
                config.trace_output.resolve(),
                (root / ".atlas-skill" / "interactive").resolve(),
            )
            self.assertEqual(config.atlas_model, "interactive-session")
            self.assertEqual(config.project_scope, "auto")
            self.assertEqual(config.session_selector, "prompt")
            self.assertEqual(config.selector_surface, "browser")
            self.assertEqual(config.learning_backend, "codex_subagent")
            self.assertIsNone(config.openai_api_key_env)
            self.assertTrue(
                (root / ".agents" / "skills" / SKILL_NAME / "SKILL.md").is_file()
            )

    def test_install_main_preserves_configured_selector_surface(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "atlas.json"
            configured = replace(
                self.base_config(root),
                session_selector="prompt",
                selector_surface="inline",
            )
            config_path.write_text(
                json.dumps(configured.to_dict()),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                code = install_main(
                    [
                        "--config",
                        str(config_path),
                        "--project-dir",
                        str(root),
                    ]
                )

            self.assertEqual(code, 0)
            installed = CodexConfig.load(root / ".codex" / "atlas-skill.json")
            self.assertEqual(installed.selector_surface, "inline")

    def test_install_main_selector_surface_flag_overrides_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "atlas.json"
            configured = replace(
                self.base_config(root),
                session_selector="prompt",
                selector_surface="browser",
            )
            config_path.write_text(
                json.dumps(configured.to_dict()),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                code = install_main(
                    [
                        "--config",
                        str(config_path),
                        "--project-dir",
                        str(root),
                        "--selector-surface",
                        "inline",
                    ]
                )

            self.assertEqual(code, 0)
            installed = CodexConfig.load(root / ".codex" / "atlas-skill.json")
            self.assertEqual(installed.selector_surface, "inline")

    def test_user_level_install_rejects_project_target(self):
        with self.assertRaises(SystemExit):
            install_main(["--user-level", "--project-dir", "."])

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

    def test_uninstall_preserves_unrelated_config_reference(self):
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
                            "command": "python backups/atlas-skill.json",
                        }
                    ]
                }
            )
            hooks_path.write_text(json.dumps(data), encoding="utf-8")

            uninstall(root)

            cleaned = json.loads(hooks_path.read_text(encoding="utf-8"))
            self.assertIn("backups/atlas-skill.json", json.dumps(cleaned))

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

    def test_resume_recovers_missed_inline_choice_before_browser_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = self.selector_config(root)
            event = {
                "session_id": "selector-resume-recovery",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }
            session_start(
                {**event, "hook_event_name": "SessionStart"},
                config,
            )
            append_text(transcript, "Inspect the existing experiment.", role="user")
            append_text(transcript, "MAST", role="user")

            browser_config = replace(config, selector_surface="browser")
            with patch(
                "atlas_integration.codex.runtime.start_browser_picker"
            ) as launch:
                resumed = session_start(
                    {**event, "hook_event_name": "SessionStart"},
                    browser_config,
                )

            launch.assert_not_called()
            state = load_state(config.trace_output, event["session_id"])
            self.assertEqual(state["selection"]["status"], "selected")
            self.assertEqual(
                state["selection"]["selected_taxonomy_id"],
                "mast",
            )
            self.assertEqual(
                state["selector_recovery"]["source"],
                "transcript",
            )
            self.assertIn(
                "taxonomy is pinned to MAST",
                resumed["hookSpecificOutput"]["additionalContext"],
            )
            self.assertIn("recovered", resumed["systemMessage"].lower())

    def test_browser_catalog_waits_for_user_prompt_and_applies_directly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            result_path = root / "browser-result.json"
            config = replace(
                self.selector_config(root),
                selector_surface="browser",
            )
            event = {
                "session_id": "selector-browser",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }

            picker = {
                "pid": 123,
                "url": "http://127.0.0.1:43210/",
                "result_path": str(result_path),
            }
            with (
                patch(
                    "atlas_integration.codex.runtime.start_browser_picker",
                    return_value=picker,
                ) as launch,
                patch(
                    "atlas_integration.codex.runtime.open_browser_picker",
                    return_value=True,
                ) as opened,
            ):
                started = session_start(
                    {**event, "hook_event_name": "SessionStart"}, config
                )
                self.assertIsNone(started)
                self.assertFalse(config.trace_output.exists())
                launch.assert_not_called()
                opened.assert_not_called()

                started = user_prompt_submit(
                    {
                        **event,
                        "hook_event_name": "UserPromptSubmit",
                        "prompt": "Inspect the project.",
                    },
                    config,
                )
            self.assertIn("taxonomy library opened", started["systemMessage"])
            launch.assert_called_once()
            opened.assert_called_once_with(picker)
            waiting = load_state(config.trace_output, event["session_id"])
            self.assertEqual(waiting["selection"]["status"], "browser_pending")
            self.assertEqual(
                waiting["selection"]["pending_task"],
                "Inspect the project.",
            )

            apply_browser_choice(
                {
                    "version": 1,
                    "session_id": event["session_id"],
                    "trace_output": str(config.trace_output),
                    "store_dir": str(config.store_dir),
                    "selection": waiting["selection"],
                    "event": {
                        "cwd": str(root),
                        "session_id": event["session_id"],
                    },
                    "routing_root": str(config.trace_output),
                    "default_trace_output": str(config.trace_output),
                    "task_group": config.task_group,
                    "project_scope": config.project_scope,
                    "project_id": config.project_id,
                    "result_path": str(result_path),
                },
                "tax-django-orm-001",
            )
            state = load_state(config.trace_output, event["session_id"])
            self.assertEqual(state["selection"]["status"], "selected")
            self.assertEqual(
                state["selection"]["selected_taxonomy_id"],
                "tax-django-orm-001",
            )

    def test_legacy_pending_selector_refreshes_before_parsing_old_number(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = self.selector_config(root)
            event = {
                "session_id": "selector-refresh",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }
            session_start({**event, "hook_event_name": "SessionStart"}, config)
            state = load_state(config.trace_output, event["session_id"])
            state["selection"].pop("version", None)
            state["selection"]["options"] = [
                state["selection"]["options"][0],
                *state["selection"]["catalog_options"],
                state["selection"]["options"][-1],
            ]
            save_state(config.trace_output, event["session_id"], state)

            refreshed = user_prompt_submit(
                {
                    **event,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "2",
                },
                config,
            )
            context = refreshed["hookSpecificOutput"]["additionalContext"]
            self.assertIn("2. web-backend", context)
            self.assertIn("8. No taxonomy", context)
            updated = load_state(config.trace_output, event["session_id"])
            self.assertEqual(updated["selection"]["status"], "pending")

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
            self.assertIn("ATLAS selected web-backend", json.dumps(chosen))
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
            self.assertIn("web-backend  [Recommended]", context)
            self.assertNotIn("tax-flask-routing-004", context)
            self.assertIn("2. MAST", context)
            self.assertIn("3. No taxonomy", context)
            self.assertIn("learn a new taxonomy from zero", context)

    def test_mast_in_bound_project_routes_conversation_to_fresh_group(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            transcript = root / "codex.jsonl"
            transcript.write_text("", encoding="utf-8")
            raw_config = replace(
                self.selector_config(root),
                trace_output=root / "atlas-home",
                project_scope="auto",
            )

            first = {
                "session_id": "shared-taxonomy",
                "cwd": str(root),
                "transcript_path": str(transcript),
            }
            shared_config = raw_config.for_event(first)
            session_start(
                {**first, "hook_event_name": "SessionStart"}, shared_config
            )
            user_prompt_submit(
                {
                    **first,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "tax-django-orm-001",
                },
                shared_config,
            )
            user_prompt_submit(
                {
                    **first,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Inspect the ORM.",
                },
                shared_config,
            )
            shared_program = shared_config.trace_output
            self.assertEqual(
                ProgramWorkspace(shared_program).load()["taxonomy_id"],
                "tax-django-orm-001",
            )

            fresh_event = {
                **first,
                "session_id": "fresh-taxonomy-conversation",
            }
            before_choice = raw_config.for_event(fresh_event)
            shown = session_start(
                {**fresh_event, "hook_event_name": "SessionStart"},
                before_choice,
            )
            context = shown["hookSpecificOutput"]["additionalContext"]
            self.assertIn("1. web-backend  [Recommended]", context)
            self.assertIn("2. MAST", context)

            accepted = user_prompt_submit(
                {
                    **fresh_event,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "MAST",
                },
                before_choice,
            )
            self.assertIn(
                "existing shared project taxonomy remains unchanged",
                json.dumps(accepted),
            )

            routed = raw_config.for_event(fresh_event)
            self.assertNotEqual(routed.trace_output, shared_program)
            self.assertTrue(routed.task_group.startswith("fresh-"))
            selected = load_state(routed.trace_output, fresh_event["session_id"])
            self.assertEqual(selected["selection"]["status"], "selected")
            self.assertEqual(
                selected["selection"]["shared_taxonomy_preserved"],
                "tax-django-orm-001",
            )

            user_prompt_submit(
                {
                    **fresh_event,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Build a separate workflow.",
                },
                routed,
            )
            fresh_state = load_state(
                routed.trace_output,
                fresh_event["session_id"],
            )
            self.assertEqual(fresh_state["taxonomy_id"], "mast")
            self.assertEqual(
                ProgramWorkspace(shared_program).load()["taxonomy_id"],
                "tax-django-orm-001",
            )

            third = {**first, "session_id": "still-shared-default"}
            third_config = raw_config.for_event(third)
            self.assertEqual(third_config.trace_output, shared_program)
            next_selector = session_start(
                {**third, "hook_event_name": "SessionStart"}, third_config
            )
            self.assertIn(
                "web-backend  [Recommended]",
                next_selector["hookSpecificOutput"]["additionalContext"],
            )

    def test_optional_skill_install_uninstall_still_works(self):
        with tempfile.TemporaryDirectory() as temp:
            skills_dir = Path(temp) / "skills"
            result = install_skill(skills_dir=skills_dir)
            self.assertEqual(result.skill_dir, skills_dir / SKILL_NAME)
            self.assertTrue(result.skill_md.exists())
            summary = uninstall_skill(skills_dir=skills_dir)
            self.assertIn(str(result.skill_md), summary["removed"])
            self.assertFalse(result.skill_md.exists())

    def test_skill_reinstall_updates_an_atlas_managed_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            skills_dir = Path(temp) / "skills"
            first = install_skill(skills_dir=skills_dir)
            first.skill_md.write_text("outdated managed skill", encoding="utf-8")

            second = install_skill(skills_dir=skills_dir)

            self.assertEqual(second.skill_dir, first.skill_dir)
            self.assertNotEqual(
                second.skill_md.read_text(encoding="utf-8"),
                "outdated managed skill",
            )

    def test_skill_install_refuses_an_unmanaged_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            skills_dir = Path(temp) / "skills"
            skill_dir = skills_dir / SKILL_NAME
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("user skill", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                install_skill(skills_dir=skills_dir)

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
