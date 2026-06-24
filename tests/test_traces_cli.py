"""Trace-management CLI tests."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from atlas_runtime.traces import GenerationTrace, TraceStore
from atlas_runtime.traces_cli import collection_status, export_traces, prune_traces


def sample_trace(problem_id: str) -> GenerationTrace:
    return GenerationTrace(
        problem_id=problem_id,
        task=f"task {problem_id}",
        raw_trajectory=f"trajectory {problem_id}",
        metadata={"fixture": True},
    )


class TraceCliTests(unittest.TestCase):
    def test_status_lists_taxonomy_and_pending_collections(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            TraceStore(root / "traces" / "tax-alpha").append_many(
                [sample_trace("one")]
            )
            TraceStore(root / "program" / "pending").append_many(
                [sample_trace("pending")]
            )
            rows = collection_status(
                trace_root=root / "traces",
                trace_output=root / "program",
            )
        by_name = {row["collection"]: row for row in rows}
        self.assertEqual(by_name["tax-alpha"]["total_records"], 1)
        self.assertEqual(by_name["program-pending"]["total_records"], 1)

    def test_export_returns_canonical_trace_records(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            TraceStore(root / "traces" / "tax-alpha").append_many(
                [sample_trace("one"), sample_trace("two")]
            )
            records = export_traces("tax-alpha", trace_root=root / "traces")
        self.assertEqual(
            {record["problem_id"] for record in records},
            {"one", "two"},
        )
        self.assertEqual(
            set(records[0]),
            {"problem_id", "task", "raw_trajectory", "metadata"},
        )

    def test_prune_is_dry_run_until_confirmed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = TraceStore(root / "traces" / "tax-alpha")
            names = store.append_many_with_names([sample_trace("old")])
            path = store.root / names[0]
            old = time.time() - 10 * 86_400
            os.utime(path, (old, old))

            dry = prune_traces(
                trace_root=root / "traces",
                taxonomy_id="tax-alpha",
                older_than_days=7,
                confirm=False,
            )
            self.assertTrue(path.exists())
            self.assertEqual(dry["matched"], 1)
            self.assertEqual(dry["deleted"], 0)

            deleted = prune_traces(
                trace_root=root / "traces",
                taxonomy_id="tax-alpha",
                older_than_days=7,
                confirm=True,
            )
            self.assertFalse(path.exists())
            self.assertEqual(deleted["matched"], 1)
            self.assertEqual(deleted["deleted"], 1)

    def test_export_cli_writes_jsonl_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            TraceStore(root / "traces" / "tax-alpha").append_many(
                [sample_trace("one")]
            )
            output = root / "out.jsonl"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "atlas_runtime.traces_cli",
                    "export",
                    "--trace-root",
                    str(root / "traces"),
                    "--taxonomy-id",
                    "tax-alpha",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            lines = output.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["problem_id"], "one")


if __name__ == "__main__":
    unittest.main()
