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
from atlas_integration.codex.runtime import session_start as codex_session_start
from atlas_integration.codex.state import save_state as save_codex_state
from atlas_integration.interactive.selector import (
    build_selection,
    render_active_selection_context,
)
from atlas_runtime import ProgramWorkspace
from atlas_runtime.project_scope import project_program_path
from finding import mast, store, webview


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

    def test_learned_taxonomy_replaces_mast_in_host_context(self) -> None:
        config = CodexConfig(
            trace_output=self.routing_root,
            atlas_model="test-model",
            store_dir=STORE_DIR,
            trace_root=self.root / "traces",
            dashboard=False,
            project_scope="auto",
            task_group="default",
            session_selector="prompt",
            selector_surface="inline",
        )
        event = {
            "hook_event_name": "SessionStart",
            "thread_id": "codex-learned-thread",
            "cwd": str(self.project),
            "transcript_path": str(self.transcript),
        }
        scoped = config.for_event(event)
        taxonomy_id = str(store.list_all(STORE_DIR)[0]["taxonomy_id"])
        record = store.fetch_by_id(taxonomy_id, STORE_DIR)
        ProgramWorkspace(scoped.trace_output).bind_inherited_taxonomy(taxonomy_id)
        selection = build_selection(
            trace_output=self.root / "unbound-selection",
            store_dir=STORE_DIR,
            cwd=self.project,
            catalog_mode="inline",
        )
        selection.update(
            status="selected",
            selected_kind="mast",
            selected_taxonomy_id=mast.MAST_ID,
            selected_label="MAST",
        )
        save_codex_state(
            scoped.trace_output,
            "codex-learned-thread",
            {
                "version": 1,
                "session_id": "codex-learned-thread",
                "conversation_id": "codex-learned-thread",
                "episode_sequence": 6,
                "taxonomy_id": taxonomy_id,
                "selection": selection,
                "finished": True,
            },
        )

        output = codex_session_start(event, scoped)
        context = output["hookSpecificOutput"]["additionalContext"]

        self.assertIn("ATLAS active taxonomy is", context)
        self.assertIn(store.display_name(record), context)
        self.assertIn(taxonomy_id, context)
        self.assertIn("selected MAST lineage", context)
        self.assertIn("Use only codes from the active taxonomy", context)
        self.assertNotIn("taxonomy is pinned to MAST", context)

    def test_claude_context_names_learned_taxonomy_after_activation(self) -> None:
        config = self.config(selector_surface="inline")
        event = {
            "hook_event_name": "SessionStart",
            "session_id": "claude-learned-session",
            "cwd": str(self.project),
            "transcript_path": str(self.transcript),
        }
        scoped = config.for_event(event)
        taxonomy_id = str(store.list_all(STORE_DIR)[0]["taxonomy_id"])
        record = store.fetch_by_id(taxonomy_id, STORE_DIR)
        ProgramWorkspace(scoped.trace_output).bind_inherited_taxonomy(taxonomy_id)
        selection = build_selection(
            trace_output=self.root / "unbound-claude-selection",
            store_dir=STORE_DIR,
            cwd=self.project,
            catalog_mode="inline",
        )
        selection.update(
            status="selected",
            selected_kind="mast",
            selected_taxonomy_id=mast.MAST_ID,
            selected_label="MAST",
        )
        save_state(
            scoped.trace_output,
            "claude-learned-session",
            {
                "version": 1,
                "session_id": "claude-learned-session",
                "conversation_id": "claude-learned-session",
                "episode_sequence": 6,
                "taxonomy_id": taxonomy_id,
                "selection": selection,
                "finished": True,
            },
        )

        output = session_start(event, scoped)
        context = output["hookSpecificOutput"]["additionalContext"]

        self.assertIn("ATLAS active taxonomy is", context)
        self.assertIn(store.display_name(record), context)
        self.assertIn(taxonomy_id, context)
        self.assertIn("selected MAST lineage", context)
        self.assertNotIn("taxonomy is pinned to MAST", context)

    def test_shared_context_preserves_seed_when_no_successor_is_active(self) -> None:
        selection = {
            "selected_taxonomy_id": mast.MAST_ID,
            "selected_label": "MAST",
        }

        context = render_active_selection_context(
            selection,
            active_taxonomy_id=mast.MAST_ID,
            store_dir=STORE_DIR,
        )

        self.assertIn("taxonomy is pinned to MAST", context)

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
