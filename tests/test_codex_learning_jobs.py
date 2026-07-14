from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from finding import store

from atlas_integration.codex.learning_jobs import (
    drain_learning_notices,
    enqueue_learning_job,
    reconcile_learning_jobs,
)
from atlas_integration.codex.native_worker import run_worker
from atlas_runtime import GenerationTrace, ProgramWorkspace
from atlas_runtime.traces import TraceStore


class CodexLearningJobTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.program = self.root / "program"
        self.store_dir = self.root / "taxonomies"
        self.trace_root = self.root / "traces"
        self.workspace = ProgramWorkspace(self.program, repo="demo-project")
        self.launched: list[Path] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _append_pending(self, start: int, count: int) -> list[str]:
        return self.workspace.pending.append_many_with_names(
            GenerationTrace(
                problem_id=f"episode-{index}",
                task=f"Task {index}",
                raw_trajectory=f"Observed failure in completed episode {index}",
                metadata={"outcome": "hidden", "episode": index},
            )
            for index in range(start, start + count)
        )

    def _enqueue(self, kind: str = "generation") -> tuple[str, Path]:
        job_id = enqueue_learning_job(
            self.workspace,
            kind=kind,
            store_dir=self.store_dir,
            trace_root=self.trace_root,
            task_group="default",
            conversation_id="conversation-1",
            codex_cli_path=sys.executable,
            launcher=self.launched.append,
        )
        return job_id, self.program / "learning_jobs" / job_id

    @staticmethod
    def _candidate(snapshot: dict, *, suffix: str = "") -> dict:
        trace_ids = [item["problem_id"] for item in snapshot["traces"]]
        return {
            "decision": "replace",
            "repo": snapshot["repo"],
            "domain": "Small-company operations tooling",
            "summary": "Failures that recur while building integrated company tools.",
            "codes": [
                {
                    "id": f"OPS-1{suffix}",
                    "name": f"Simulation mistaken for integration{suffix}",
                    "description": "The UI appears complete while persistence is absent.",
                    "category": "C",
                    "evidence": {
                        "trace_ids": trace_ids,
                        "rationale": "Each cited episode exposed a missing durable boundary.",
                    },
                }
            ],
        }

    def _complete_worker(self, job_dir: Path, candidate: dict) -> list[str]:
        commands: list[str] = []

        def runner(command, *, prompt, job_dir, timeout_seconds):
            commands.extend(command)
            (job_dir / "candidate.json").write_text(
                json.dumps(candidate), encoding="utf-8"
            )
            return SimpleNamespace(returncode=0)

        self.assertEqual(run_worker(job_dir, runner=runner), 0)
        return commands

    def test_generation_snapshot_is_immutable_and_queue_is_idempotent(self) -> None:
        self._append_pending(1, 5)
        job_id, job_dir = self._enqueue()
        snapshot_before = (job_dir / "snapshot.json").read_bytes()
        self._append_pending(6, 1)

        duplicate_id, duplicate_dir = self._enqueue()

        self.assertEqual(duplicate_id, job_id)
        self.assertEqual(duplicate_dir, job_dir)
        self.assertEqual((job_dir / "snapshot.json").read_bytes(), snapshot_before)
        snapshot = json.loads(snapshot_before)
        self.assertEqual(len(snapshot["traces"]), 5)
        self.assertTrue(all("outcome" not in trace["metadata"] for trace in snapshot["traces"]))
        self.assertEqual(self.launched, [job_dir])
        notices = drain_learning_notices(self.workspace, "conversation-1")
        self.assertEqual(len(notices), 1)
        self.assertIn("taxonomy generation triggered", notices[0])
        self.assertEqual(drain_learning_notices(self.workspace, "conversation-1"), [])

    def test_legacy_codex_learning_state_migrates_without_losing_notices(self) -> None:
        notice = {
            "id": "legacy-notice",
            "conversation_id": "conversation-1",
            "text": "Legacy learning notice",
        }
        with self.workspace.locked_manifest() as manifest:
            manifest["codex_learning"] = {
                "active_job_id": None,
                "jobs": {"legacy-job": {"state": "failed"}},
                "notices": [notice],
            }

        self.assertEqual(
            drain_learning_notices(self.workspace, "conversation-1"),
            ["Legacy learning notice"],
        )

        manifest = self.workspace.load()
        self.assertNotIn("codex_learning", manifest)
        self.assertEqual(
            manifest["interactive_learning"]["jobs"],
            {"legacy-job": {"state": "failed"}},
        )
        self.assertEqual(manifest["interactive_learning"]["notices"], [])

    def test_generation_activates_valid_receipt_and_preserves_later_trace(self) -> None:
        source_names = self._append_pending(1, 5)
        _, job_dir = self._enqueue()
        later_name = self._append_pending(6, 1)[0]
        snapshot = json.loads((job_dir / "snapshot.json").read_text(encoding="utf-8"))
        command = self._complete_worker(job_dir, self._candidate(snapshot))

        reconcile_learning_jobs(
            self.workspace,
            store_dir=self.store_dir,
            trace_root=self.trace_root,
        )

        manifest = self.workspace.load()
        taxonomy_id = manifest["taxonomy_id"]
        self.assertTrue(taxonomy_id.startswith("tax-codex-"))
        self.assertTrue(store.exists(taxonomy_id, self.store_dir))
        self.assertEqual(self.workspace.pending.count(), 0)
        self.assertEqual(
            sorted(path.name for path in (self.trace_root / taxonomy_id).glob("trace-*.json")),
            sorted(source_names + [later_name]),
        )
        self.assertEqual(manifest["refinement"]["traces_since_refinement"], 1)
        self.assertEqual(
            manifest["refinement"]["trace_refs"],
            [{"taxonomy_id": taxonomy_id, "filename": later_name}],
        )
        self.assertIn("--disable", command)
        self.assertIn("hooks", command)
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertNotIn("OPENAI_API_KEY", " ".join(command))
        completion = drain_learning_notices(self.workspace, "conversation-1")
        self.assertEqual(len(completion), 2)  # trigger was intentionally not drained
        self.assertIn("taxonomy generation finished", completion[-1])
        self.assertIn(taxonomy_id, completion[-1])
        self.assertEqual(drain_learning_notices(self.workspace, "conversation-1"), [])

    def test_invalid_evidence_is_rejected_without_activation(self) -> None:
        self._append_pending(1, 5)
        _, job_dir = self._enqueue()
        snapshot = json.loads((job_dir / "snapshot.json").read_text(encoding="utf-8"))
        candidate = self._candidate(snapshot)
        candidate["codes"][0]["evidence"]["trace_ids"] = ["not-in-snapshot"]
        self._complete_worker(job_dir, candidate)

        reconcile_learning_jobs(
            self.workspace,
            store_dir=self.store_dir,
            trace_root=self.trace_root,
        )

        self.assertIsNone(self.workspace.load()["taxonomy_id"])
        self.assertEqual(self.workspace.pending.count(), 5)
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["state"], "rejected")
        notices = drain_learning_notices(self.workspace, "conversation-1")
        self.assertIn("MAST remains active", notices[-1])

    def test_oversized_candidate_is_rejected_without_activation(self) -> None:
        self._append_pending(1, 5)
        _, job_dir = self._enqueue()
        snapshot = json.loads((job_dir / "snapshot.json").read_text(encoding="utf-8"))
        candidate = self._candidate(snapshot)
        template = candidate["codes"][0]
        candidate["codes"] = [
            {
                **template,
                "id": f"OPS-{index}",
                "name": f"Failure mode {index}",
            }
            for index in range(31)
        ]
        self._complete_worker(job_dir, candidate)

        reconcile_learning_jobs(
            self.workspace,
            store_dir=self.store_dir,
            trace_root=self.trace_root,
        )

        self.assertIsNone(self.workspace.load()["taxonomy_id"])
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["state"], "rejected")
        self.assertIn("at most 30 codes", job["last_error"])

    def test_failed_worker_retries_same_snapshot_and_job_id(self) -> None:
        self._append_pending(1, 5)
        job_id, job_dir = self._enqueue()

        def failed_runner(*_args, **_kwargs):
            return SimpleNamespace(returncode=9)

        self.assertEqual(run_worker(job_dir, runner=failed_runner), 1)
        reconcile_learning_jobs(
            self.workspace,
            store_dir=self.store_dir,
            trace_root=self.trace_root,
        )
        retried_id, retried_dir = self._enqueue()
        self.assertEqual(retried_id, job_id)
        snapshot = json.loads((job_dir / "snapshot.json").read_text(encoding="utf-8"))
        self._complete_worker(retried_dir, self._candidate(snapshot, suffix="-R"))
        reconcile_learning_jobs(
            self.workspace,
            store_dir=self.store_dir,
            trace_root=self.trace_root,
        )
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["state"], "activated")
        self.assertEqual(job["attempts"], 2)

    def test_dead_worker_lease_expires_without_disabling_mast(self) -> None:
        self._append_pending(1, 5)
        _, job_dir = self._enqueue()
        job_path = job_dir / "job.json"
        job = json.loads(job_path.read_text(encoding="utf-8"))
        job["state"] = "running"
        job["worker_timeout_seconds"] = 1
        job["updated_at_unix"] = 1
        job_path.write_text(json.dumps(job), encoding="utf-8")

        reconcile_learning_jobs(
            self.workspace,
            store_dir=self.store_dir,
            trace_root=self.trace_root,
        )

        expired = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(expired["state"], "failed")
        self.assertIsNone(self.workspace.load()["taxonomy_id"])
        notices = drain_learning_notices(self.workspace, "conversation-1")
        self.assertIn("MAST remains active", notices[-1])

    def test_launch_failure_emits_trigger_and_finished_notices(self) -> None:
        self._append_pending(1, 5)

        def broken_launcher(_job_dir: Path) -> None:
            raise OSError("worker executable is unavailable")

        with self.assertRaisesRegex(OSError, "worker executable"):
            enqueue_learning_job(
                self.workspace,
                kind="generation",
                store_dir=self.store_dir,
                trace_root=self.trace_root,
                task_group="default",
                conversation_id="conversation-1",
                codex_cli_path=sys.executable,
                launcher=broken_launcher,
            )

        notices = drain_learning_notices(self.workspace, "conversation-1")
        self.assertEqual(len(notices), 2)
        self.assertIn("taxonomy generation triggered", notices[0])
        self.assertIn("taxonomy generation finished", notices[1])
        self.assertIn("MAST remains active", notices[1])
        manifest = self.workspace.load()
        self.assertIsNone(manifest["interactive_learning"]["active_job_id"])
        job_path = next((self.program / "learning_jobs").glob("*/job.json"))
        job = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(job["state"], "failed")
        self.assertEqual(job["attempts"], 1)

    def test_active_episode_delays_activation(self) -> None:
        self._append_pending(1, 5)
        _, job_dir = self._enqueue()
        snapshot = json.loads((job_dir / "snapshot.json").read_text(encoding="utf-8"))
        self._complete_worker(job_dir, self._candidate(snapshot))
        self.workspace.register_session("still-running", "mast")

        reconcile_learning_jobs(
            self.workspace,
            store_dir=self.store_dir,
            trace_root=self.trace_root,
        )
        self.assertIsNone(self.workspace.load()["taxonomy_id"])
        self.assertEqual(
            json.loads((job_dir / "job.json").read_text(encoding="utf-8"))["state"],
            "activating",
        )

        self.workspace.finish_session("still-running")
        reconcile_learning_jobs(
            self.workspace,
            store_dir=self.store_dir,
            trace_root=self.trace_root,
        )
        self.assertIsNotNone(self.workspace.load()["taxonomy_id"])

    def test_manifest_write_failure_resumes_same_activation(self) -> None:
        self._append_pending(1, 5)
        _, job_dir = self._enqueue()
        snapshot = json.loads((job_dir / "snapshot.json").read_text(encoding="utf-8"))
        self._complete_worker(job_dir, self._candidate(snapshot))
        real_replace = __import__("os").replace
        failed = False

        def fail_manifest_once(source, destination):
            nonlocal failed
            if Path(destination).name == ".atlas-program.json" and not failed:
                failed = True
                raise OSError("injected manifest replacement failure")
            return real_replace(source, destination)

        with patch("atlas_runtime.program.os.replace", side_effect=fail_manifest_once):
            reconcile_learning_jobs(
                self.workspace,
                store_dir=self.store_dir,
                trace_root=self.trace_root,
            )
        self.assertIsNone(self.workspace.load()["taxonomy_id"])
        interrupted = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(interrupted["state"], "activating")

        reconcile_learning_jobs(
            self.workspace,
            store_dir=self.store_dir,
            trace_root=self.trace_root,
        )
        recovered = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(recovered["state"], "activated")
        self.assertEqual(self.workspace.load()["taxonomy_id"], recovered["taxonomy_id"])

    def test_refinement_consumes_only_frozen_refs(self) -> None:
        parent_id = "tax-parent"
        store.register(
            {
                "taxonomy_id": parent_id,
                "repo": "demo-project",
                "domain": "Operations",
                "summary": "Original taxonomy",
                "codes": [
                    {
                        "id": "OPS-OLD",
                        "name": "Old mode",
                        "description": "Original description",
                        "category": "A",
                    }
                ],
            },
            self.store_dir,
        )
        self.workspace.bind_inherited_taxonomy(parent_id)
        parent_traces = TraceStore(self.trace_root / parent_id)
        frozen_names = parent_traces.append_many_with_names(
            GenerationTrace(
                problem_id=f"refine-{index}",
                task=f"Refinement {index}",
                raw_trajectory=f"New recurring failure {index}",
            )
            for index in range(1, 3)
        )
        self.workspace.add_refinement_traces(parent_id, frozen_names)
        _, job_dir = self._enqueue("refinement")
        later_name = parent_traces.append_many_with_names(
            [
                GenerationTrace(
                    problem_id="refine-later",
                    task="Later episode",
                    raw_trajectory="This arrived after the frozen review window.",
                )
            ]
        )[0]
        self.workspace.add_refinement_traces(parent_id, [later_name])
        snapshot = json.loads((job_dir / "snapshot.json").read_text(encoding="utf-8"))
        self._complete_worker(job_dir, self._candidate(snapshot, suffix="-NEW"))

        reconcile_learning_jobs(
            self.workspace,
            store_dir=self.store_dir,
            trace_root=self.trace_root,
        )

        manifest = self.workspace.load()
        self.assertNotEqual(manifest["taxonomy_id"], parent_id)
        self.assertEqual(manifest["refinement"]["traces_since_refinement"], 1)
        self.assertEqual(
            manifest["refinement"]["trace_refs"],
            [{"taxonomy_id": parent_id, "filename": later_name}],
        )
        self.assertEqual(manifest["refinement"]["rounds_completed"], 1)

    def test_stale_refinement_is_rejected_before_successor_side_effects(self) -> None:
        parent_id = "tax-parent"
        store.register(
            {
                "taxonomy_id": parent_id,
                "repo": "demo-project",
                "domain": "Operations",
                "codes": [
                    {
                        "id": "OPS-OLD",
                        "name": "Old mode",
                        "description": "Original description",
                        "category": "A",
                    }
                ],
            },
            self.store_dir,
        )
        self.workspace.bind_inherited_taxonomy(parent_id)
        parent_traces = TraceStore(self.trace_root / parent_id)
        name = parent_traces.append_many_with_names(
            [
                GenerationTrace(
                    problem_id="refine-1",
                    task="Refinement",
                    raw_trajectory="Evidence for a possible successor.",
                )
            ]
        )[0]
        self.workspace.add_refinement_traces(parent_id, [name])
        _, job_dir = self._enqueue("refinement")
        snapshot = json.loads((job_dir / "snapshot.json").read_text(encoding="utf-8"))
        self._complete_worker(job_dir, self._candidate(snapshot, suffix="-STALE"))
        self.workspace.follow_taxonomy_successor("tax-unrelated")

        reconcile_learning_jobs(
            self.workspace,
            store_dir=self.store_dir,
            trace_root=self.trace_root,
        )

        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["state"], "rejected")
        self.assertEqual(self.workspace.load()["taxonomy_id"], "tax-unrelated")
        self.assertFalse(store.exists(job["taxonomy_id"], self.store_dir))


if __name__ == "__main__":
    unittest.main()
