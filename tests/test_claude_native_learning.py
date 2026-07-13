from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from finding import store

from atlas_integration.claude_code.config import ClaudeCodeConfig
from atlas_integration.claude_code.dispatcher import _merge_notices
from atlas_integration.claude_code.install import install
from atlas_integration.claude_code.learning_jobs import (
    drain_learning_notices,
    enqueue_claude_learning_job,
    reconcile_learning_jobs,
)
from atlas_integration.claude_code.native_worker import run_worker
from atlas_integration.claude_code.runtime import session_start, user_prompt_submit
from atlas_integration.claude_code.state import load_state
from atlas_integration.claude_code.uninstall import uninstall
from atlas_integration.codex.config import CodexConfig
from atlas_runtime import GenerationTrace, ProgramWorkspace


ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = ROOT / "tests" / "fixtures" / "taxonomies"


class ClaudeNativeLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base_program = self.root / "atlas-home"
        self.project = self.root / "project"
        self.project.mkdir()
        self.transcript = self.root / "transcript.jsonl"
        self.transcript.write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def config(self, **changes) -> ClaudeCodeConfig:
        fields = {
            "trace_output": self.base_program,
            "atlas_model": "test-model",
            "store_dir": STORE_DIR,
            "trace_root": self.root / "traces",
            "dashboard": False,
            "session_selector": "prompt",
            "learning_backend": "claude_subagent",
            "claude_cli_path": Path(sys.executable),
        }
        fields.update(changes)
        return ClaudeCodeConfig(**fields)

    def event(self, name: str, **changes) -> dict:
        value = {
            "hook_event_name": name,
            "session_id": "claude-session-1",
            "cwd": str(self.project),
            "transcript_path": str(self.transcript),
        }
        value.update(changes)
        return value

    def test_selector_holds_task_then_starts_mast_episode(self) -> None:
        config = self.config()
        output = session_start(self.event("SessionStart"), config)
        self.assertIn("Which taxonomy", output["systemMessage"])
        self.assertIn("No taxonomy", output["systemMessage"])

        blocked = user_prompt_submit(
            self.event("UserPromptSubmit", prompt="Build the company tools demo"),
            config,
        )
        self.assertEqual(blocked["decision"], "block")
        self.assertIn("Which taxonomy", blocked["reason"])
        state = load_state(config.trace_output, "claude-session-1")
        self.assertEqual(
            state["selection"]["pending_task"],
            "Build the company tools demo",
        )

        accepted = user_prompt_submit(
            self.event("UserPromptSubmit", prompt="MAST"),
            config,
        )
        self.assertIn("ATLAS selected MAST", accepted["systemMessage"])
        self.assertIn(
            "Build the company tools demo",
            accepted["hookSpecificOutput"]["additionalContext"],
        )
        state = load_state(config.trace_output, "claude-session-1")
        self.assertEqual(state["selection"]["status"], "selected")
        self.assertEqual(state["episode_task"], "Build the company tools demo")
        self.assertFalse(state["finished"])

    def test_codex_and_claude_auto_scope_share_program_path(self) -> None:
        claude = self.config(project_scope="auto", task_group="platform")
        codex = CodexConfig(
            trace_output=self.base_program,
            atlas_model="test-model",
            store_dir=STORE_DIR,
            trace_root=self.root / "traces",
            dashboard=False,
            project_scope="auto",
            task_group="platform",
        )
        event = {"cwd": str(self.project)}
        self.assertEqual(
            claude.for_event(event).trace_output,
            codex.for_event(event).trace_output,
        )

    def test_claude_worker_proposes_and_foreground_reconcile_activates(self) -> None:
        program = self.root / "program"
        trace_root = self.root / "worker-traces"
        taxonomy_store = self.root / "worker-taxonomies"
        workspace = ProgramWorkspace(program, repo="company-tools")
        workspace.pending.append_many_with_names(
            GenerationTrace(
                problem_id=f"episode-{index}",
                task=f"Task {index}",
                raw_trajectory=f"Failure evidence {index}",
            )
            for index in range(1, 6)
        )
        launched: list[Path] = []
        job_id = enqueue_claude_learning_job(
            workspace,
            kind="generation",
            store_dir=taxonomy_store,
            trace_root=trace_root,
            task_group="default",
            conversation_id="claude-session-1",
            claude_cli_path=sys.executable,
            launcher=launched.append,
        )
        job_dir = program / "learning_jobs" / job_id
        snapshot = json.loads((job_dir / "snapshot.json").read_text(encoding="utf-8"))
        candidate = {
            "decision": "replace",
            "repo": snapshot["repo"],
            "domain": "Small-company operations",
            "summary": "Recurring integration failures.",
            "codes": [
                {
                    "id": "OPS-1",
                    "name": "Demo boundary confusion",
                    "description": "A simulation is presented as a live integration.",
                    "category": "C",
                    "evidence": {
                        "trace_ids": [item["problem_id"] for item in snapshot["traces"]],
                        "rationale": "Every frozen episode exposed this boundary.",
                    },
                }
            ],
        }
        commands: list[str] = []

        def runner(command, **_kwargs):
            commands.extend(command)
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"structured_output": candidate}),
                stderr="",
            )

        self.assertEqual(run_worker(job_dir, runner=runner), 0)
        reconcile_learning_jobs(
            workspace,
            store_dir=taxonomy_store,
            trace_root=trace_root,
        )
        taxonomy_id = workspace.load()["taxonomy_id"]
        self.assertTrue(taxonomy_id.startswith("tax-claude-"))
        self.assertEqual(
            store.fetch_by_id(taxonomy_id, taxonomy_store)["provenance"]["driver"],
            "claude_subagent",
        )
        self.assertIn("--safe-mode", commands)
        self.assertIn("--tools", commands)
        self.assertIn("--no-session-persistence", commands)
        self.assertIn("--json-schema", commands)
        self.assertNotIn("ANTHROPIC_API_KEY", " ".join(commands))
        notices = drain_learning_notices(workspace, "claude-session-1")
        self.assertIn("taxonomy generation triggered", notices[0])
        self.assertIn("taxonomy generation finished", notices[-1])

    def test_notice_merging_is_visible_to_user_and_agent(self) -> None:
        merged = _merge_notices(
            None,
            event_name="Stop",
            notices=["ATLAS taxonomy refinement finished"],
        )
        self.assertIn("refinement finished", merged["systemMessage"])
        self.assertIn(
            "refinement finished",
            merged["hookSpecificOutput"]["additionalContext"],
        )

    def test_user_level_install_preserves_unrelated_settings(self) -> None:
        claude_home = self.root / ".claude"
        claude_home.mkdir()
        settings_path = claude_home / "settings.json"
        settings_path.write_text(
            json.dumps({"effortLevel": "high", "enabledPlugins": {"demo": True}}),
            encoding="utf-8",
        )
        with patch(
            "atlas_integration.claude_code.install.Path.home",
            return_value=self.root,
        ):
            result = install(
                self.root,
                self.config(project_scope="auto"),
                verify=False,
                user_level=True,
            )
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(settings["effortLevel"], "high")
        self.assertTrue(settings["enabledPlugins"]["demo"])
        self.assertIn("UserPromptSubmit", settings["hooks"])
        self.assertEqual(result["scope"], "user")

        with patch(
            "atlas_integration.claude_code.uninstall.Path.home",
            return_value=self.root,
        ):
            removed = uninstall(self.root, user_level=True)
        remaining = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(remaining["effortLevel"], "high")
        self.assertTrue(remaining["enabledPlugins"]["demo"])
        self.assertNotIn("hooks", remaining)
        self.assertTrue(removed["config_removed"])
        self.assertEqual(removed["scope"], "user")


if __name__ == "__main__":
    unittest.main()
