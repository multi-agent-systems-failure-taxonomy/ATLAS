"""Tests for the --skip-judge flag and its plumbing.

Confirms the flag flows through:
  * options.RuntimeOptions / parse_runtime_args
  * generation.run_generation_job (overrides taxonomy_check)
  * lifecycle.Session (round-trip)
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_runtime import generation, options


def _structural_taxonomy() -> dict:
    """A trivially-acceptable taxonomy that structurally_accept() returns True for."""
    return {
        "annotation_layer": {
            "category_a": [{"code": "A.1", "name": "Loop", "definition": "..."}],
            "category_b": [],
            "category_c": [{"code": "C.1", "name": "Math", "definition": "..."}],
        },
        "full_layer": {
            "domain_info": {"domain": {"name": "test-domain"}},
            "category_a": {"A.1": {"code": "A.1", "name": "Loop", "definition": "..."}},
            "category_b": {},
            "category_c": {"C.1": {"code": "C.1", "name": "Math", "definition": "..."}},
        },
    }


class ParseRuntimeArgsTests(unittest.TestCase):
    def test_skip_judge_defaults_false(self) -> None:
        opts = options.parse_runtime_args(
            ["--trace-output", "/tmp/x", "--atlas-model", "m"]
        )
        self.assertFalse(opts.skip_judge)

    def test_skip_judge_flag_parsed(self) -> None:
        opts = options.parse_runtime_args(
            ["--trace-output", "/tmp/x", "--atlas-model", "m", "--skip-judge"]
        )
        self.assertTrue(opts.skip_judge)


class GenerationSkipJudgeTests(unittest.TestCase):
    """skip_judge=True must bypass the taxonomy_check pass even when enabled."""

    def test_skip_judge_overrides_taxonomy_check_true(self) -> None:
        # If skip_judge=True is honored, check_taxonomy MUST NOT be called.
        captured = {"called": False}

        def fake_check(*_, **__):
            captured["called"] = True
            raise AssertionError("check_taxonomy should not run when skip_judge=True")

        # Use a stub generator so we don't call the real ATLAS pipeline.
        def stub_generator(_traces):
            return _structural_taxonomy()

        with tempfile.TemporaryDirectory() as td:
            ws_dir = Path(td) / "ws"
            store_dir = Path(td) / "store"
            trace_root = Path(td) / "traces"
            from atlas_runtime.program import ProgramWorkspace
            from atlas_runtime.traces import GenerationTrace
            ws = ProgramWorkspace(ws_dir)
            for i in range(5):  # meet generation_threshold
                ws.pending.append_many([
                    GenerationTrace(problem_id=f"p{i}", task="t",
                                    raw_trajectory="r", metadata={})
                ])
            # Mark generation in 'running' state so run_generation_job proceeds.
            ws.try_begin_generation()

            with patch.object(generation, "check_taxonomy", fake_check):
                result = generation.run_generation_job(
                    ws,
                    store_dir=store_dir,
                    trace_root=trace_root,
                    generator=stub_generator,
                    atlas_model="stub-model",
                    taxonomy_check=True,
                    skip_judge=True,  # the flag under test
                    generation_threshold=5,
                    activation_poll_seconds=0.001,
                    activation_timeout_seconds=2.0,
                )

            self.assertFalse(captured["called"],
                             "check_taxonomy must NOT be called when skip_judge=True")
            self.assertEqual(result.action, "activated")
            self.assertIsNotNone(result.taxonomy_id)


class SessionSkipJudgeRoundTripTests(unittest.TestCase):
    def test_session_carries_skip_judge_into_lifecycle(self) -> None:
        from atlas_runtime import lifecycle
        with tempfile.TemporaryDirectory() as td:
            ws_dir = Path(td) / "ws"
            store_dir = Path(td) / "store"
            session = lifecycle.start_session(
                trace_output=ws_dir,
                store_dir=store_dir,
                atlas_model="stub",
                skip_judge=True,
                dashboard=False,
            )
            self.assertTrue(session.skip_judge)


if __name__ == "__main__":
    unittest.main()
