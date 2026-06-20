"""Taxonomy-check generation acceptance and rejection retry lifecycle."""

import json
import tempfile
import unittest
from pathlib import Path

from atlas_runtime.generation import run_generation_job, trigger_generation
from atlas_runtime.program import ProgramWorkspace
from atlas_runtime.traces import GenerationTrace

TRACE_FIXTURE = Path(__file__).parent / "fixtures" / "atlas_generation_trace.json"


def trace(number: int) -> GenerationTrace:
    record = json.loads(TRACE_FIXTURE.read_text(encoding="utf-8"))
    record["problem_id"] = f"retry-{number}"
    return GenerationTrace.from_dict(record)


def raw_taxonomy():
    return {
        "category_definitions": {"A": "Generated"},
        "annotation_layer": {
            "category_a": [
                {
                    "code": f"A.{i}",
                    "name": f"Mode_{i}",
                    "definition": f"Failure mode {i}",
                }
                for i in range(1, 6)
            ],
            "category_b": [],
            "category_c": [],
        },
    }


def judge_with_codes(prompt, count):
    units = []
    for line in prompt.splitlines():
        if line.startswith("### UNIT "):
            unit_id = line.split("### UNIT ", 1)[1].split(" ", 1)[0]
            units.append(
                {
                    "unit_id": unit_id,
                    "codes_fired": [
                        {"code": f"A.{i}", "evidence": "observed"}
                        for i in range(1, count + 1)
                    ],
                }
            )
    return json.dumps({"per_unit": units})


class TaxonomyCheckLifecycleTests(unittest.TestCase):
    def test_rejection_waits_for_n_new_traces_then_uses_all(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = ProgramWorkspace(root / "program")
            workspace.pending.append_many([trace(i) for i in range(5)])
            workspace.try_begin_generation()
            generated_sizes = []

            result = run_generation_job(
                workspace,
                store_dir=root / "taxonomies",
                trace_root=root / "traces",
                atlas_model="claude-sonnet-4-6",
                generator=lambda traces: (
                    generated_sizes.append(len(traces)) or raw_taxonomy()
                ),
                judge_call=lambda prompt, model: judge_with_codes(prompt, 2),
                generation_threshold=5,
            )
            self.assertEqual(result.action, "rejected")
            self.assertEqual(workspace.generation_retry_after(5), 10)

            workspace.pending.append_many([trace(i) for i in range(5, 9)])
            held = trigger_generation(
                workspace,
                threshold=5,
                generation_stops=True,
                store_dir=root / "taxonomies",
                trace_root=root / "traces",
                atlas_model="claude-sonnet-4-6",
                generator=lambda traces: raw_taxonomy(),
                judge_call=lambda prompt, model: judge_with_codes(prompt, 5),
            )
            self.assertEqual(held.action, "none")

            workspace.pending.append_many([trace(9)])
            accepted = trigger_generation(
                workspace,
                threshold=5,
                generation_stops=True,
                store_dir=root / "taxonomies",
                trace_root=root / "traces",
                atlas_model="claude-sonnet-4-6",
                generator=lambda traces: (
                    generated_sizes.append(len(traces)) or raw_taxonomy()
                ),
                judge_call=lambda prompt, model: judge_with_codes(prompt, 5),
            )
            self.assertEqual(accepted.action, "activated")
            self.assertEqual(generated_sizes, [5, 10])

    def test_rejection_retries_immediately_when_n_arrived_during_check(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = ProgramWorkspace(root / "program")
            workspace.pending.append_many([trace(0), trace(1)])
            workspace.try_begin_generation()
            generation_sizes = []
            judge_round = {"value": 0}

            def generator(traces):
                generation_sizes.append(len(traces))
                return raw_taxonomy()

            def judge(prompt, model):
                judge_round["value"] += 1
                if judge_round["value"] == 1:
                    workspace.pending.append_many([trace(2), trace(3)])
                    return judge_with_codes(prompt, 2)
                return judge_with_codes(prompt, 5)

            result = run_generation_job(
                workspace,
                store_dir=root / "taxonomies",
                trace_root=root / "traces",
                atlas_model="claude-sonnet-4-6",
                generator=generator,
                judge_call=judge,
                generation_threshold=2,
            )
            self.assertEqual(result.action, "activated")
            self.assertEqual(generation_sizes, [2, 4])

    def test_taxonomy_check_false_skips_judge(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = ProgramWorkspace(root / "program")
            workspace.pending.append_many([trace(0)])
            workspace.try_begin_generation()

            def should_not_run(_prompt, _model):
                raise AssertionError("judge must not run")

            result = run_generation_job(
                workspace,
                store_dir=root / "taxonomies",
                trace_root=root / "traces",
                atlas_model="claude-sonnet-4-6",
                taxonomy_check=False,
                generator=lambda traces: raw_taxonomy(),
                judge_call=should_not_run,
                generation_threshold=1,
            )
            self.assertEqual(result.action, "activated")


if __name__ == "__main__":
    unittest.main()
