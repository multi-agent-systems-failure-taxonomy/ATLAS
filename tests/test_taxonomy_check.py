"""Frozen snapshot, adaptive batching, and generated-taxonomy verdict tests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_runtime.models import ModelProfile, resolve_model_profile
from atlas_runtime.program import ProgramWorkspace
from atlas_runtime.taxonomy_check import check_taxonomy
from atlas_runtime.traces import GenerationTrace

TRACE_FIXTURE = Path(__file__).parent / "fixtures" / "atlas_generation_trace.json"


def trace(number: int, text: str | None = None) -> GenerationTrace:
    record = json.loads(TRACE_FIXTURE.read_text(encoding="utf-8"))
    record["problem_id"] = f"check-{number}"
    if text is not None:
        record["raw_trajectory"] = text
    return GenerationTrace.from_dict(record)


def candidate(count: int = 5):
    return {
        "repo": "",
        "domain": "",
        "codes": [
            {
                "id": f"C.{i}",
                "name": f"Mode {i}",
                "description": f"Failure mode {i}",
                "category": "Test",
            }
            for i in range(1, count + 1)
        ],
    }


def judge_all(prompt, _model):
    units = []
    for line in prompt.splitlines():
        if line.startswith("### UNIT "):
            unit_id = line.split("### UNIT ", 1)[1].split(" ", 1)[0]
            units.append(
                {
                    "unit_id": unit_id,
                    "codes_fired": [
                        {"code": f"C.{i}", "evidence": "observed"}
                        for i in range(1, 6)
                    ],
                }
            )
    return json.dumps({"per_unit": units})


class TaxonomyCheckTests(unittest.TestCase):
    def test_accepts_five_codes_firing_at_least_once(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = ProgramWorkspace(td)
            workspace.pending.append_many([trace(1), trace(2)])
            result = check_taxonomy(
                workspace,
                candidate(),
                atlas_model="claude-sonnet-4-6",
                judge_call=judge_all,
            )
            self.assertTrue(result.accepted)
            self.assertEqual(len(result.active_codes), 5)
            self.assertTrue(
                all(code["support_tier"] == "ACTIVE"
                    for code in result.candidate["codes"])
            )
            self.assertEqual(
                len(list((workspace.root / "checks").glob("*.result.json"))),
                1,
            )

    def test_rejects_when_fewer_than_five_codes_fire(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = ProgramWorkspace(td)
            workspace.pending.append_many([trace(1)])

            def judge_two(prompt, model):
                payload = json.loads(judge_all(prompt, model))
                for item in payload["per_unit"]:
                    item["codes_fired"] = item["codes_fired"][:2]
                return json.dumps(payload)

            result = check_taxonomy(
                workspace,
                candidate(),
                atlas_model="claude-sonnet-4-6",
                judge_call=judge_two,
            )
            self.assertFalse(result.accepted)
            self.assertEqual(result.active_codes, ["C.1", "C.2"])

    def test_snapshot_ignores_trace_added_while_judge_runs(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = ProgramWorkspace(td)
            workspace.pending.append_many([trace(1)])

            def adding_judge(prompt, model):
                workspace.pending.append_many([trace(2)])
                return judge_all(prompt, model)

            result = check_taxonomy(
                workspace,
                candidate(),
                atlas_model="claude-sonnet-4-6",
                judge_call=adding_judge,
            )
            self.assertEqual(result.snapshot_count, 1)
            self.assertEqual(workspace.pending.count(), 2)

    def test_large_trace_is_chunked_but_counts_once_per_code(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = ProgramWorkspace(td)
            workspace.pending.append_many([trace(1, "failure " * 500)])
            calls = []

            def counting_judge(prompt, model):
                calls.append(prompt)
                return judge_all(prompt, model)

            with patch(
                "atlas_runtime.taxonomy_check.resolve_model_profile",
                return_value=ModelProfile(
                    context_tokens=500,
                    output_reserve_tokens=50,
                    safety_ratio=0.9,
                ),
            ):
                result = check_taxonomy(
                    workspace,
                    candidate(),
                    atlas_model="claude-sonnet-4-6",
                    judge_call=counting_judge,
                )
            self.assertGreater(len(calls), 1)
            self.assertTrue(result.accepted)
            self.assertTrue(
                all(code["support"] == 1 for code in result.candidate["codes"])
            )

    def test_batches_no_more_than_four_trace_units(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = ProgramWorkspace(td)
            workspace.pending.append_many([trace(i) for i in range(9)])
            sizes = []

            def count_units(prompt, model):
                sizes.append(prompt.count("### UNIT "))
                return judge_all(prompt, model)

            check_taxonomy(
                workspace,
                candidate(),
                atlas_model="claude-sonnet-4-6",
                judge_call=count_units,
            )
            self.assertEqual(sizes, [4, 4, 1])

    def test_recognized_model_profiles(self):
        self.assertEqual(
            resolve_model_profile("claude-sonnet-4-6").context_tokens,
            200_000,
        )
        with self.assertRaises(ValueError):
            resolve_model_profile("mystery-model")

    def test_invalid_judge_output_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = ProgramWorkspace(td)
            workspace.pending.append_many([trace(1)])
            result = check_taxonomy(
                workspace,
                candidate(),
                atlas_model="claude-sonnet-4-6",
                judge_call=lambda _prompt, _model: "not json",
                max_retries=1,
            )
            self.assertFalse(result.accepted)
            self.assertGreater(result.failed_units, 0)

    def test_verbatim_quote_survives_jsonl_backslash_escaping(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = ProgramWorkspace(td)
            raw = (
                '{"toolUseResult":"Error: File does not exist. '
                'cwd C:\\\\Users\\\\andre\\\\work"}'
            )
            workspace.pending.append_many(
                [
                    GenerationTrace(
                        problem_id="escaped",
                        task="read a file",
                        raw_trajectory=raw,
                        metadata={},
                    )
                ]
            )

            def judge(prompt, _model):
                unit_id = next(
                    line.split("### UNIT ", 1)[1].split(" ", 1)[0]
                    for line in prompt.splitlines()
                    if line.startswith("### UNIT ")
                )
                return json.dumps(
                    {
                        "per_unit": [
                            {
                                "unit_id": unit_id,
                                "codes_fired": [
                                    {
                                        "code": "C.1",
                                        "quote": (
                                            "Error: File does not exist. "
                                            "cwd C:\\Users\\andre\\work"
                                        ),
                                        "evidence": "the read path failed",
                                    }
                                ],
                            }
                        ]
                    }
                )

            result = check_taxonomy(
                workspace,
                candidate(),
                atlas_model="claude-sonnet-4-6",
                judge_call=judge,
                min_active_codes=1,
            )
            self.assertTrue(result.accepted)
            self.assertEqual(result.active_codes, ["C.1"])


if __name__ == "__main__":
    unittest.main()
