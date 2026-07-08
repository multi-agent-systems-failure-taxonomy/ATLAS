"""Program health/status surface."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from atlas_runtime.program import ProgramWorkspace
from atlas_runtime.status import main, program_health
from atlas_runtime.traces import GenerationTrace


class ProgramHealthTests(unittest.TestCase):
    def test_program_health_reads_manifest_pending_and_decisions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            program = root / "program"
            workspace = ProgramWorkspace(program, repo="repo")
            workspace.pending.append_many([
                GenerationTrace(
                    problem_id="p1",
                    task="task",
                    raw_trajectory="trajectory",
                )
            ])
            (program / "decisions.log").write_text(
                "old\nnew\n", encoding="utf-8",
            )

            health = program_health(program)

            self.assertTrue(health["manifest_exists"])
            self.assertEqual(health["program_id"], workspace.program_id)
            self.assertEqual(health["repo"], "repo")
            self.assertEqual(health["active_taxonomy_id"], "mast")
            self.assertEqual(health["pending_traces"], 1)
            self.assertEqual(health["recent_decisions"], ["old", "new"])

    def test_status_cli_json_uses_config_trace_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            program = root / "program"
            ProgramWorkspace(program)
            config = root / "atlas.json"
            config.write_text(
                json.dumps({"version": 1, "trace_output": str(program)}),
                encoding="utf-8",
            )
            self.assertEqual(main(["--config", str(config), "--json"]), 0)


if __name__ == "__main__":
    unittest.main()
