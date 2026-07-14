"""Agent- and model-agnostic lifecycle tests."""

import json
import tempfile
import unittest
from pathlib import Path

from atlas_runtime.lifecycle import (
    end_session,
    pre_submission,
    record_trace,
    start_session,
)
from atlas_runtime.program import ProgramConflict
from atlas_runtime.traces import GenerationTrace, TraceStore
from finding import resolver
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = ROOT / "tests" / "fixtures" / "taxonomies"
TRACE_FIXTURE = Path(__file__).parent / "fixtures" / "atlas_generation_trace.json"


def real_trace() -> GenerationTrace:
    return GenerationTrace.from_dict(
        json.loads(TRACE_FIXTURE.read_text(encoding="utf-8"))
    )


class LifecycleTests(unittest.TestCase):
    def test_trace_output_is_mandatory(self):
        with self.assertRaises((TypeError, ValueError)):
            start_session(resolver.ABSENT, trace_output=None)

    def test_session_start_delivers_mast_and_protocol(self):
        with tempfile.TemporaryDirectory() as td:
            session = start_session(
                resolver.ABSENT,
                trace_output=td,
                store_dir=STORE_DIR,
                session_id="session-1",
            )
            self.assertEqual(session.delivery.taxonomy_id, "mast")
            self.assertEqual(session.delivery.taxonomy["taxonomy_id"], "mast")
            self.assertFalse(session.generation_stops)
            self.assertIn(
                "ATLAS pre-submission gate",
                session.delivery.runtime_protocol,
            )

    def test_session_automatically_starts_dashboard(self):
        with tempfile.TemporaryDirectory() as td:
            with patch(
                "atlas_runtime.dashboard.ensure_dashboard",
                return_value="http://127.0.0.1:9999/",
            ) as ensure:
                session = start_session(
                    resolver.ABSENT,
                    trace_output=td,
                    store_dir=STORE_DIR,
                    repo="owner/project",
                )
            ensure.assert_called_once()
            self.assertEqual(
                session.delivery.dashboard_url,
                "http://127.0.0.1:9999/",
            )

    def test_session_start_loads_and_binds_explicit_taxonomy(self):
        with tempfile.TemporaryDirectory() as td:
            session = start_session(
                "tax-django-orm-001",
                trace_output=td,
                store_dir=STORE_DIR,
                session_id="session-2",
            )
            self.assertEqual(session.delivery.taxonomy_id, "tax-django-orm-001")
            self.assertEqual(session.delivery.taxonomy["repo"], "django/django")
            self.assertEqual(
                session.workspace.load()["taxonomy_id"],
                "tax-django-orm-001",
            )

    def test_same_trace_output_reuses_program_and_taxonomy(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as tr:
            first = start_session(
                "tax-django-orm-001",
                trace_output=td,
                store_dir=STORE_DIR,
                trace_root=tr,
            )
            program_id = first.program_id
            end_session(first)
            second = start_session(
                resolver.ABSENT,
                trace_output=td,
                store_dir=STORE_DIR,
                trace_root=tr,
            )
            self.assertEqual(second.program_id, program_id)
            self.assertEqual(second.delivery.taxonomy_id, "tax-django-orm-001")

    def test_different_trace_outputs_create_different_programs(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one = start_session(
                resolver.ABSENT,
                trace_output=first,
                store_dir=STORE_DIR,
            )
            two = start_session(
                resolver.ABSENT,
                trace_output=second,
                store_dir=STORE_DIR,
            )
            self.assertNotEqual(one.program_id, two.program_id)

    def test_conflicting_inherited_taxonomy_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            first = start_session(
                "tax-django-orm-001",
                trace_output=td,
                store_dir=STORE_DIR,
            )
            end_session(first)
            with self.assertRaises(ProgramConflict):
                start_session(
                    "tax-numpy-array-003",
                    trace_output=td,
                    store_dir=STORE_DIR,
                )

    def test_gate_uses_session_retry_limit(self):
        with tempfile.TemporaryDirectory() as td:
            session = start_session(
                resolver.ABSENT,
                trace_output=td,
                store_dir=STORE_DIR,
                max_retries=2,
            )
            blocked = pre_submission(
                session,
                "Final ATLAS status: REPAIR_REQUIRED\nRepair attempts used: 1",
            )
            allowed = pre_submission(
                session,
                "Final ATLAS status: REPAIR_REQUIRED\nRepair attempts used: 2",
            )
            self.assertFalse(blocked.allow)
            self.assertTrue(allowed.allow)

    def test_inherited_trace_is_pending_first_then_integrated(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as tr:
            session = start_session(
                "tax-django-orm-001",
                trace_output=td,
                store_dir=STORE_DIR,
                trace_root=tr,
            )
            record_trace(session, real_trace())
            result = end_session(session)
            self.assertEqual(result.persisted_traces, 1)
            self.assertEqual(result.integrated_traces, 1)
            self.assertEqual(session.workspace.pending.count(), 0)
            self.assertEqual(
                TraceStore(Path(tr) / "tax-django-orm-001").count(),
                1,
            )

    def test_pre_persisted_trace_retry_does_not_double_count_refinement(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as tr:
            session = start_session(
                "tax-django-orm-001",
                trace_output=td,
                store_dir=STORE_DIR,
                trace_root=tr,
                k_init=20,
            )
            names = session.workspace.pending.append_many_with_names([real_trace()])

            result = end_session(
                session,
                pre_persisted_trace_names=names,
            )
            session.workspace.add_refinement_traces(
                "tax-django-orm-001",
                names,
            )

            self.assertEqual(result.persisted_traces, 1)
            self.assertEqual(result.integrated_traces, 1)
            self.assertEqual(
                session.workspace.refinement_state()["traces_since_refinement"],
                1,
            )
            self.assertEqual(
                session.workspace.refinement_state()["trace_refs"],
                [
                    {
                        "taxonomy_id": "tax-django-orm-001",
                        "filename": names[0],
                    }
                ],
            )

    def test_mast_trace_stays_pending_below_threshold(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as tr:
            session = start_session(
                resolver.ABSENT,
                trace_output=td,
                store_dir=STORE_DIR,
                trace_root=tr,
            )
            record_trace(session, real_trace())
            result = end_session(session)
            self.assertEqual(result.generation.action, "none")
            self.assertEqual(session.workspace.pending.count(), 1)
            self.assertIsNone(session.workspace.load()["taxonomy_id"])


if __name__ == "__main__":
    unittest.main()
