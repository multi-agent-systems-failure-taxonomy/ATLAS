"""Regression tests for the OfficeQA Claude Code orchestrator."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
RUNNER_PATH = ROOT / "officeqa" / "run_officeqa_atlas.py"
SPEC = importlib.util.spec_from_file_location("officeqa_runner", RUNNER_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def assistant_line(text: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": text}],
            },
        }
    )


class OfficeQARunnerTests(unittest.TestCase):
    def test_agent_command_uses_minimal_hook_compatible_claude_mode(self):
        command = runner.agent_command("claude-haiku-4-5")
        self.assertIn("--system-prompt", command)
        self.assertIn("--tools", command)
        self.assertIn("Read,Grep,Glob,Bash", command)
        self.assertIn("--setting-sources", command)
        self.assertIn("local", command)
        self.assertIn("--strict-mcp-config", command)
        self.assertIn(str(runner.EMPTY_MCP_CONFIG), command)
        self.assertIn("--disable-slash-commands", command)
        self.assertNotIn("--bare", command)
        self.assertNotIn("--safe-mode", command)

    def test_answer_comes_from_assistant_trajectory_not_prompt_or_reflection(self):
        trajectory = "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "content": (
                                "Use <FINAL_ANSWER>your answer</FINAL_ANSWER>"
                            )
                        },
                    }
                ),
                assistant_line("<FINAL_ANSWER>2,602</FINAL_ANSWER>"),
                assistant_line("Final ATLAS status: PASS"),
            ]
        )
        answer = runner.answer_from_trajectory(trajectory)
        self.assertEqual(answer, "2,602")
        self.assertTrue(runner.score_answer(answer, "2602"))

    def test_place_docs_removes_previous_task_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            corpus = root / "corpus"
            work = root / "work"
            corpus.mkdir()
            work.mkdir()
            (corpus / "old.txt").write_text("old", encoding="utf-8")
            (corpus / "new.txt").write_text("new", encoding="utf-8")
            (work / "old.txt").write_text("old", encoding="utf-8")
            with patch.object(runner, "WORK", work):
                placed = runner.place_docs(
                    {"source_files": "new.txt"},
                    corpus,
                    ["old.txt"],
                )
            self.assertEqual(placed, ["new.txt"])
            self.assertFalse((work / "old.txt").exists())
            self.assertEqual((work / "new.txt").read_text(), "new")

    def test_captured_trace_is_correlated_by_new_session_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            program = root / "program"
            session_dir = program / ".atlas-claude-code"
            pending = program / "pending"
            trace_root = root / "traces"
            session_dir.mkdir(parents=True)
            pending.mkdir()
            trace_root.mkdir()
            state_path = session_dir / "session-new.json"
            state_path.write_text(
                json.dumps(
                    {
                        "session_id": "session-new",
                        "trace_captured": True,
                    }
                ),
                encoding="utf-8",
            )
            (pending / "trace-one.json").write_text(
                json.dumps(
                    {
                        "problem_id": "claude-code:session-new",
                        "task": "task",
                        "raw_trajectory": assistant_line(
                            "<FINAL_ANSWER>44,463</FINAL_ANSWER>"
                        ),
                        "metadata": {
                            "claude_session_id": "session-new",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(runner, "PROGRAM", program),
                patch.object(runner, "SESSION_DIR", session_dir),
                patch.object(runner, "TRACE_ROOT", trace_root),
            ):
                session_id, trace = runner.captured_trace_after(
                    set(), timeout=0.1
                )
            self.assertEqual(session_id, "session-new")
            self.assertEqual(trace["task"], "task")

    def test_wait_for_learning_reports_timeout_and_failure(self):
        with tempfile.TemporaryDirectory() as td:
            program = Path(td)
            manifest = program / ".atlas-program.json"
            manifest.write_text(
                json.dumps(
                    {
                        "generation": {"state": "running"},
                        "refinement": {"state": "idle"},
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(runner, "PROGRAM", program):
                with self.assertRaises(TimeoutError):
                    runner.wait_for_learning(0)
                manifest.write_text(
                    json.dumps(
                        {
                            "generation": {
                                "state": "failed",
                                "last_error": "proxy unavailable",
                            },
                            "refinement": {"state": "idle"},
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(RuntimeError, "proxy unavailable"):
                    runner.wait_for_learning(0.1, poll=0.01)

    def test_usage_is_aggregated_from_assistant_messages(self):
        trajectory = "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [],
                            "usage": {
                                "input_tokens": 10,
                                "cache_read_input_tokens": 20,
                                "cache_creation_input_tokens": 30,
                                "output_tokens": 40,
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [],
                            "usage": {
                                "input_tokens": 1,
                                "cache_read_input_tokens": 2,
                                "cache_creation_input_tokens": 3,
                                "output_tokens": 4,
                            },
                        },
                    }
                ),
            ]
        )
        self.assertEqual(
            runner.usage_from_trajectory(trajectory),
            {
                "input_tokens": 11,
                "cache_read_input_tokens": 22,
                "cache_creation_input_tokens": 33,
                "output_tokens": 44,
            },
        )


if __name__ == "__main__":
    unittest.main()
