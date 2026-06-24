"""MAST warm-up generation lifecycle tests."""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from atlas_runtime.generation import (
    candidate_from_atlas,
    run_generation_job,
    structurally_accept,
)
from atlas_runtime.lifecycle import end_session, record_trace, start_session
from atlas_runtime.traces import GenerationTrace, TraceStore
from finding import resolver, store

ROOT = Path(__file__).resolve().parent.parent
BASE_STORE = ROOT / "tests" / "fixtures" / "taxonomies"
TRACE_FIXTURE = Path(__file__).parent / "fixtures" / "atlas_generation_trace.json"
ATLAS_OUTPUT = Path(__file__).parent / "fixtures" / "real_atlas_generation_output.json"


def trace(number: int) -> GenerationTrace:
    record = json.loads(TRACE_FIXTURE.read_text(encoding="utf-8"))
    record["problem_id"] = f"warmup-{number}"
    return GenerationTrace.from_dict(record)


def real_generation_output():
    return json.loads(ATLAS_OUTPUT.read_text(encoding="utf-8"))


def copy_store(destination: Path) -> None:
    destination.mkdir()
    for source in BASE_STORE.glob("*.json"):
        (destination / source.name).write_bytes(source.read_bytes())


class GenerationLifecycleTests(unittest.TestCase):
    def _finish_four(self, output, store_dir, trace_root):
        for number in range(4):
            session = start_session(
                resolver.ABSENT,
                trace_output=output,
                store_dir=store_dir,
                trace_root=trace_root,
            )
            record_trace(session, trace(number))
            result = end_session(session)
            self.assertEqual(result.generation.action, "none")

    def test_blocking_generation_activates_only_after_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output, store_dir, trace_root = root / "program", root / "tax", root / "traces"
            copy_store(store_dir)
            self._finish_four(output, store_dir, trace_root)
            seen_candidate = {}

            def approve(candidate):
                seen_candidate.update(candidate)
                self.assertNotIn("taxonomy_id", candidate)
                return True

            fifth = start_session(
                resolver.ABSENT,
                trace_output=output,
                store_dir=store_dir,
                trace_root=trace_root,
                generation_stops=True,
                atlas_model="claude-sonnet-4-6",
                taxonomy_check=False,
            )
            record_trace(fifth, trace(5))
            result = end_session(
                fifth,
                generator=lambda _traces: real_generation_output(),
                approver=approve,
            )

            self.assertEqual(result.generation.action, "activated")
            taxonomy_id = result.generation.taxonomy_id
            self.assertTrue(taxonomy_id)
            self.assertEqual(fifth.workspace.pending.count(), 0)
            self.assertEqual(TraceStore(trace_root / taxonomy_id).count(), 5)
            self.assertTrue(store.exists(taxonomy_id, store_dir))
            self.assertEqual(fifth.workspace.load()["taxonomy_id"], taxonomy_id)
            self.assertEqual(
                fifth.workspace.refinement_state()["traces_since_refinement"],
                0,
            )
            self.assertEqual(seen_candidate["repo"], fifth.workspace.repo)
            self.assertEqual(
                seen_candidate["domain"],
                "Software Engineering / Code Repair",
            )

            first_new_task = start_session(
                resolver.ABSENT,
                trace_output=output,
                store_dir=store_dir,
                trace_root=trace_root,
                k_init=2,
                k=20,
                refinement_stops=True,
            )
            self.assertEqual(first_new_task.delivery.taxonomy_id, taxonomy_id)
            record_trace(first_new_task, trace(6))
            first_new_result = end_session(
                first_new_task,
                refiner=lambda current, _traces: {
                    "repo": current["repo"],
                    "domain": current["domain"],
                    "codes": current["codes"],
                },
            )
            self.assertEqual(first_new_result.refinement.action, "none")
            self.assertEqual(
                first_new_task.workspace.refinement_state()[
                    "traces_since_refinement"
                ],
                1,
            )

    def test_rejection_preserves_pending_and_creates_no_taxonomy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output, store_dir, trace_root = root / "program", root / "tax", root / "traces"
            copy_store(store_dir)
            self._finish_four(output, store_dir, trace_root)
            before = {path.name for path in store_dir.glob("*.json")}

            fifth = start_session(
                resolver.ABSENT,
                trace_output=output,
                store_dir=store_dir,
                trace_root=trace_root,
                generation_stops=True,
                atlas_model="claude-sonnet-4-6",
                taxonomy_check=False,
            )
            record_trace(fifth, trace(5))
            result = end_session(
                fifth,
                generator=lambda _traces: real_generation_output(),
                approver=lambda _candidate: False,
            )

            self.assertEqual(result.generation.action, "rejected")
            self.assertEqual(fifth.workspace.pending.count(), 5)
            self.assertIsNone(fifth.workspace.load()["taxonomy_id"])
            self.assertEqual(
                {path.name for path in store_dir.glob("*.json")},
                before,
            )
            self.assertFalse(trace_root.exists())

    def test_generation_failure_preserves_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output, store_dir, trace_root = root / "program", root / "tax", root / "traces"
            copy_store(store_dir)
            self._finish_four(output, store_dir, trace_root)

            fifth = start_session(
                resolver.ABSENT,
                trace_output=output,
                store_dir=store_dir,
                trace_root=trace_root,
                generation_stops=True,
                atlas_model="claude-sonnet-4-6",
                taxonomy_check=False,
            )
            record_trace(fifth, trace(5))

            def broken(_traces):
                raise RuntimeError("generator unavailable")

            result = end_session(fifth, generator=broken)
            self.assertEqual(result.generation.action, "failed")
            self.assertEqual(fifth.workspace.pending.count(), 5)
            self.assertIsNone(fifth.workspace.load()["taxonomy_id"])

    def test_nonblocking_generation_keeps_mast_until_job_activates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output, store_dir, trace_root = root / "program", root / "tax", root / "traces"
            copy_store(store_dir)
            self._finish_four(output, store_dir, trace_root)
            launched = []

            fifth = start_session(
                resolver.ABSENT,
                trace_output=output,
                store_dir=store_dir,
                trace_root=trace_root,
                atlas_model="claude-sonnet-4-6",
                taxonomy_check=False,
            )
            record_trace(fifth, trace(5))
            result = end_session(
                fifth,
                background_launcher=lambda: launched.append(True),
            )
            self.assertEqual(result.generation.action, "started")
            self.assertEqual(launched, [True])
            self.assertIsNone(fifth.workspace.load()["taxonomy_id"])

            next_task = start_session(
                resolver.ABSENT,
                trace_output=output,
                store_dir=store_dir,
                trace_root=trace_root,
            )
            self.assertEqual(next_task.delivery.taxonomy_id, "mast")

            outcome = {}

            def worker():
                outcome["result"] = run_generation_job(
                    fifth.workspace,
                    store_dir=store_dir,
                    trace_root=trace_root,
                    generator=lambda _traces: real_generation_output(),
                    atlas_model="claude-sonnet-4-6",
                    taxonomy_check=False,
                    activation_poll_seconds=0.01,
                    activation_timeout_seconds=2,
                )

            thread = threading.Thread(target=worker)
            thread.start()
            time.sleep(0.05)
            self.assertIsNone(fifth.workspace.load()["taxonomy_id"])
            end_session(next_task)
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcome["result"].action, "activated")

            later = start_session(
                resolver.ABSENT,
                trace_output=output,
                store_dir=store_dir,
                trace_root=trace_root,
            )
            self.assertEqual(
                later.delivery.taxonomy_id,
                outcome["result"].taxonomy_id,
            )


class AtlasCandidateConversionTests(unittest.TestCase):
    def test_keeps_step_one_discovered_domain(self):
        candidate = candidate_from_atlas(real_generation_output())
        self.assertEqual(
            candidate["domain"],
            "Software Engineering / Code Repair",
        )
        self.assertTrue(structurally_accept(candidate))

    def test_missing_domain_metadata_remains_valid_display_empty_string(self):
        raw = real_generation_output()
        raw.pop("full_layer")
        candidate = candidate_from_atlas(raw)
        self.assertEqual(candidate["domain"], "")
        self.assertTrue(structurally_accept(candidate))

    def test_codes_are_canonical_with_short_category(self):
        candidate = candidate_from_atlas(real_generation_output())
        self.assertTrue(candidate["codes"])
        for code in candidate["codes"]:
            # category is the SHORT label, never the verbose definition sentence
            self.assertIn(code["category"], {"A", "B", "C"})
            self.assertEqual(
                {"id", "name", "description", "category"} - set(code), set()
            )


if __name__ == "__main__":
    unittest.main()
