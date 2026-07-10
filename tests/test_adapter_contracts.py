"""Shared behavioral contract for hook adapters.

These tests deliberately exercise Claude Code and Codex through the same
scenario so adapter-specific fixes do not silently land in only one sibling.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from atlas_integration.claude_code.config import ClaudeCodeConfig
from atlas_integration.claude_code.hooks import session_start as claude_start
from atlas_integration.claude_code.hooks import stop as claude_stop
from atlas_integration.codex.config import CodexConfig
from atlas_integration.codex.runtime import session_start as codex_start
from atlas_integration.codex.runtime import stop as codex_stop
from atlas_runtime.evidence import EVIDENCE_FILE

ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = ROOT / "tests" / "fixtures" / "taxonomies"


@dataclass(frozen=True)
class AdapterCase:
    name: str
    make_config: Callable[[Path], Any]
    session_start: Callable[[dict, Any], Any]
    stop_first: Callable[[dict, Any], tuple[int, str] | dict]
    stop_second: Callable[[dict, Any], tuple[int, str] | dict]


def _append_transcript(path: Path, text: str, *, role: str = "assistant") -> None:
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


def _checkpoint_id(prompt: str) -> str:
    match = re.search(r"Checkpoint ID:\s*(\S+)", prompt)
    assert match, prompt
    return match.group(1)


def _clean_final_report(checkpoint_id: str) -> str:
    return f"""ATLAS reflection:
- Checkpoint ID: {checkpoint_id}
- Observe: The final answer was checked.
- Map:
  - none apply | considered: MAST-12 | evidence: "verification is present"
- Correlate: The verification failure mode does not occur.
- Decide: no change needed, because verification is present.

Final ATLAS status: READY_TO_SUBMIT
Codes checked: MAST-12
Evidence: verification is present
Repair attempts used: 0
Final decision: submit
"""


class AdapterContractTests(unittest.TestCase):
    def cases(self) -> tuple[AdapterCase, ...]:
        return (
            AdapterCase(
                name="claude_code",
                make_config=lambda root: ClaudeCodeConfig(
                    trace_output=root / "program",
                    atlas_model="test-model",
                    store_dir=STORE_DIR,
                    dashboard=False,
                ),
                session_start=lambda event, config: claude_start.handle(event, config),
                stop_first=lambda event, config: claude_stop.handle(event, config),
                stop_second=lambda event, config: claude_stop.handle(
                    {**event, "stop_hook_active": True}, config
                ),
            ),
            AdapterCase(
                name="codex",
                make_config=lambda root: CodexConfig(
                    trace_output=root / "program",
                    atlas_model="test-model",
                    store_dir=STORE_DIR,
                    dashboard=False,
                ),
                session_start=codex_start,
                stop_first=codex_stop,
                stop_second=codex_stop,
            ),
        )

    def test_session_start_stop_gate_and_evidence_contract(self):
        for case in self.cases():
            with self.subTest(adapter=case.name):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    transcript = root / "transcript.jsonl"
                    transcript.write_text("", encoding="utf-8")
                    config = case.make_config(root)
                    event = {
                        "hook_event_name": "SessionStart",
                        "session_id": f"{case.name}-session",
                        "cwd": str(root),
                        "transcript_path": str(transcript),
                    }

                    start = case.session_start(event, config)
                    rendered_start = json.dumps(start) if isinstance(start, dict) else str(start)
                    self.assertIn("ATLAS runtime interaction is active", rendered_start)

                    _append_transcript(transcript, "Solve the task.", role="user")
                    _append_transcript(transcript, "Verified final answer.")
                    first = case.stop_first(
                        {**event, "hook_event_name": "Stop"},
                        config,
                    )
                    if isinstance(first, tuple):
                        code, prompt = first
                        self.assertEqual(code, 2)
                    else:
                        self.assertEqual(first["decision"], "block")
                        prompt = first["reason"]
                    cid = _checkpoint_id(prompt)
                    _append_transcript(transcript, _clean_final_report(cid))

                    second = case.stop_second(
                        {**event, "hook_event_name": "Stop"},
                        config,
                    )
                    if isinstance(second, tuple):
                        code, _message = second
                        self.assertEqual(code, 0)
                    else:
                        self.assertTrue(second["continue"])

                    evidence = json.loads(
                        (config.trace_output / EVIDENCE_FILE).read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(len(evidence["checkpoints"]), 1)


if __name__ == "__main__":
    unittest.main()
