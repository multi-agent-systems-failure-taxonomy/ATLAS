from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

from atlas_integration.claude_code.config import ClaudeCodeConfig
from atlas_integration.claude_code.runtime import session_start, user_prompt_submit
from atlas_integration.claude_code.state import save_state
from atlas_integration.codex.config import CodexConfig
from atlas_integration.interactive.selector import build_selection
from atlas_runtime.project_scope import project_program_path
from finding import mast, webview


STORE_DIR = Path(__file__).resolve().parent / "fixtures" / "taxonomies"


class ConversationScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.routing_root = self.root / "atlas-home"
        self.project = self.root / "project"
        self.project.mkdir()
        self.transcript = self.root / "transcript.jsonl"
        self.transcript.write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def config(self, *, selector_surface: str) -> ClaudeCodeConfig:
        return ClaudeCodeConfig(
            trace_output=self.routing_root,
            atlas_model="test-model",
            store_dir=STORE_DIR,
            trace_root=self.root / "traces",
            dashboard=False,
            project_scope="auto",
            session_selector="prompt",
            selector_surface=selector_surface,
            learning_backend="claude_subagent",
        )

    def event(self, name: str, cwd: Path) -> dict:
        return {
            "hook_event_name": name,
            "session_id": "claude-resume-session",
            "cwd": str(cwd),
            "transcript_path": str(self.transcript),
        }

    def test_resumed_conversation_keeps_scope_after_cwd_changes(self) -> None:
        config = self.config(selector_surface="inline")
        original_event = self.event("SessionStart", self.project)
        original = config.for_event(original_event)
        session_start(original_event, original)
        user_prompt_submit(
            {**original_event, "hook_event_name": "UserPromptSubmit", "prompt": "MAST"},
            original,
        )
        other_project = self.root / "other-project"
        other_project.mkdir()
        resumed_event = self.event("SessionStart", other_project)

        resumed = config.for_event(resumed_event)

        self.assertEqual(resumed.trace_output, original.trace_output)
        with patch(
            "atlas_integration.claude_code.runtime.start_browser_picker"
        ) as open_picker:
            output = session_start(resumed_event, resumed)
        open_picker.assert_not_called()
        self.assertIn(
            "ATLAS taxonomy is pinned to MAST",
            output["hookSpecificOutput"]["additionalContext"],
        )

    def test_legacy_selected_state_migrates_before_resume_prompt(self) -> None:
        config = self.config(selector_surface="browser")
        original_program = project_program_path(
            self.routing_root,
            cwd=self.project,
            task_group="default",
        )
        selection = build_selection(
            trace_output=original_program,
            store_dir=STORE_DIR,
            cwd=self.project,
            catalog_mode="browser",
        )
        selection.update(
            status="selected",
            selected_kind="mast",
            selected_taxonomy_id=mast.MAST_ID,
            selected_label="MAST",
        )
        save_state(
            original_program,
            "claude-resume-session",
            {
                "version": 1,
                "session_id": "claude-resume-session",
                "conversation_id": "claude-resume-session",
                "cwd": str(self.project),
                "episode_sequence": 4,
                "selection": selection,
                "finished": True,
            },
        )
        other_project = self.root / "resume-shell"
        other_project.mkdir()
        resumed_event = self.event("SessionStart", other_project)

        resumed = config.for_event(resumed_event)

        self.assertEqual(resumed.trace_output, original_program)
        with patch(
            "atlas_integration.claude_code.runtime.start_browser_picker"
        ) as open_picker:
            output = session_start(resumed_event, resumed)
        open_picker.assert_not_called()
        self.assertIn(
            "ATLAS taxonomy is pinned to MAST",
            output["hookSpecificOutput"]["additionalContext"],
        )

    def test_codex_conversation_scope_is_stable_after_cwd_changes(self) -> None:
        config = CodexConfig(
            trace_output=self.routing_root,
            atlas_model="test-model",
            store_dir=STORE_DIR,
            trace_root=self.root / "traces",
            dashboard=False,
            project_scope="auto",
            task_group="default",
        )
        first = config.for_event(
            {"thread_id": "codex-scope-thread", "cwd": str(self.project)}
        )
        other_project = self.root / "codex-other-project"
        other_project.mkdir()

        resumed = config.for_event(
            {"thread_id": "codex-scope-thread", "cwd": str(other_project)}
        )

        self.assertEqual(resumed.trace_output, first.trace_output)

    def test_picker_completion_names_the_active_host(self) -> None:
        choice = {
            "kind": "mast",
            "taxonomy_id": mast.MAST_ID,
            "label": "MAST",
            "description": "Built-in taxonomy",
            "domain": "General agent work",
            "origin": "Built-in",
        }
        for host_label in ("Claude Code", "Codex"):
            server, _result, done = webview.build_server(
                STORE_DIR,
                choice_options=[choice],
                picker_context={"host_label": host_label},
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_address[1]}/"
                with urlopen(url + "choose?id=mast", timeout=5) as response:
                    body = response.read().decode("utf-8")
                self.assertIn(f"Return to {host_label}", body)
                self.assertTrue(done.wait(timeout=1))
            finally:
                server.shutdown()
                thread.join()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
