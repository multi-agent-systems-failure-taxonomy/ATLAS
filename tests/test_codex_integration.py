"""Codex hook integration behavior."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from atlas_integration.codex.config import CodexConfig, parse_codex_hooks
from atlas_integration.codex.install import SKILL_NAME, install, install_skill
from atlas_integration.codex.runtime import session_start, stop
from atlas_integration.codex.state import load_state
from atlas_integration.codex.uninstall import uninstall, uninstall_skill
from atlas_runtime.evidence import EVIDENCE_FILE

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


def checkpoint_id(prompt: str) -> str:
    match = re.search(r"Checkpoint ID:\s*(\S+)", prompt)
    assert match
    return match.group(1)


class CodexIntegrationTests(unittest.TestCase):
    def base_config(self, root: Path) -> CodexConfig:
        return CodexConfig(
            trace_output=root / "program",
            atlas_model="test-model",
            store_dir=STORE_DIR,
            dashboard=False,
        )

    def test_default_hooks_can_be_customized(self):
        specs = parse_codex_hooks(
            {
                "SubagentStop": False,
                "PostToolUse": {"matchers": ["Bash", "Edit|Write"]},
            }
        )
        by_event = {spec.event: spec for spec in specs}
        self.assertFalse(by_event["SubagentStop"].enabled)
        self.assertEqual(by_event["PostToolUse"].matchers, ("Bash", "Edit|Write"))

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

    def test_stop_hook_blocks_then_accepts_markdown_final_report(self):
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
            append_text(transcript, "2 + 2 = 4. I am ready to submit.")
            blocked = stop(
                {**event, "hook_event_name": "Stop"},
                config,
            )
            self.assertEqual(blocked["decision"], "block")
            cid = checkpoint_id(blocked["reason"])
            final_report = f"""ATLAS reflection:
- Checkpoint ID: {cid}
- Observe: The arithmetic was directly checked.
- Correlate: No evidence-supported failure remains.
- Map:
  - none apply | considered: MAST-12 | evidence: "2 + 2 = 4"
- Decide: no change needed, because the answer is verified.

## Final ATLAS status

Ready for final answer.

**Codes checked:** none
**Evidence:** direct arithmetic verification
**Repair attempts used:** 0
**Final decision:** submit
"""
            append_text(transcript, final_report)
            accepted = stop(
                {
                    **event,
                    "hook_event_name": "Stop",
                    "last_assistant_message": final_report,
                },
                config,
            )
            self.assertTrue(accepted["continue"])
            state = load_state(config.trace_output, "codex-session")
            self.assertTrue(state["trace_captured"])
            evidence = json.loads(
                (config.trace_output / EVIDENCE_FILE).read_text(encoding="utf-8")
            )
            self.assertEqual(len(evidence["checkpoints"]), 1)
            self.assertEqual(state["taxonomy_id"], "mast")

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
