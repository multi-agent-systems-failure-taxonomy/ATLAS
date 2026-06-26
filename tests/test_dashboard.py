"""Persistent live taxonomy dashboard tests."""

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from atlas_runtime.dashboard import (
    RUNTIME_EVIDENCE,
    build_server,
    current_taxonomy,
    ensure_dashboard,
    stop_dashboard,
)
from atlas_runtime.lineage import TaxonomyLineage
from atlas_runtime.program import ProgramWorkspace

ROOT = Path(__file__).resolve().parent.parent
BASE_STORE = ROOT / "tests" / "fixtures" / "taxonomies"
BASE_ID = "tax-django-orm-001"
NEXT_ID = "tax-django-orm-live-002"


def copy_store(destination: Path) -> None:
    destination.mkdir()
    for source in BASE_STORE.glob("*.json"):
        (destination / source.name).write_bytes(source.read_bytes())


class DashboardDataTests(unittest.TestCase):
    def test_unbound_program_shows_mast(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = ProgramWorkspace(Path(td) / "program")
            data = current_taxonomy(workspace, BASE_STORE)
            self.assertEqual(data["taxonomy_id"], "mast")
            self.assertEqual(len(data["codes"]), 14)
            self.assertEqual(data["codes"][0]["code_id"], "MAST-1")

    def test_unbound_program_uses_program_repo_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            workspace = ProgramWorkspace(
                Path(td) / "program",
                repo="owner/project",
            )
            data = current_taxonomy(workspace, BASE_STORE)
            self.assertEqual(data["repo"], "owner/project")

    def test_bound_program_resolves_latest_successor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store_dir = root / "taxonomies"
            copy_store(store_dir)
            workspace = ProgramWorkspace(root / "program")
            workspace.bind_inherited_taxonomy(BASE_ID)
            original = json.loads(
                (store_dir / f"{BASE_ID}.json").read_text(encoding="utf-8")
            )
            successor = {**original, "taxonomy_id": NEXT_ID}
            (store_dir / f"{NEXT_ID}.json").write_text(
                json.dumps(successor), encoding="utf-8"
            )
            TaxonomyLineage(store_dir).add_successor(BASE_ID, NEXT_ID)

            data = current_taxonomy(workspace, store_dir)
            self.assertEqual(data["bound_taxonomy_id"], BASE_ID)
            self.assertEqual(data["taxonomy_id"], NEXT_ID)
            self.assertTrue(data["is_latest_successor"])

    def test_program_runtime_evidence_overlays_without_mutating_taxonomy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = ProgramWorkspace(root / "program")
            (workspace.root / RUNTIME_EVIDENCE).write_text(
                json.dumps(
                    {
                        "version": 1,
                        "checkpoints": [
                            {
                                "taxonomy_id": "mast",
                                "checkpoint_id": "cp-1",
                                "timestamp": 1,
                                "fired_codes": ["MAST-1"],
                            }
                        ],
                        "taxonomies": {
                            "mast": {
                                "codes": {
                                    "MAST-1": {
                                        "fire_count": 2,
                                        "task_firings": {"task-a": 2},
                                        "events": [
                                            {
                                                "checkpoint_id": "cp-1",
                                                "timestamp": 1,
                                                "evidence": "ignored spec",
                                                "correlate": "genuine mismatch",
                                            }
                                        ],
                                    }
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            data = current_taxonomy(workspace, BASE_STORE)
            first = data["codes"][0]
            self.assertEqual(first["fire_count"], 2)
            self.assertEqual(
                first["task_firings"],
                [{"task_id": "task-a", "label": "task-a", "count": 2}],
            )
            self.assertEqual(
                first["runtime_evidence"][0]["evidence"],
                "ignored spec",
            )
            self.assertEqual(first["runtime_evidence"][0]["seq"], 1)

    def test_task_labels_and_evidence_clipping(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = ProgramWorkspace(root / "program")
            (workspace.root / ".atlas-task-labels.json").write_text(
                json.dumps(
                    {"sess-xyz": {"label": "UID0001", "correct": True}}
                ),
                encoding="utf-8",
            )
            long_evidence = "x" * 600
            (workspace.root / RUNTIME_EVIDENCE).write_text(
                json.dumps(
                    {
                        "version": 1,
                        "taxonomies": {
                            "mast": {
                                "codes": {
                                    "MAST-1": {
                                        "fire_count": 1,
                                        "task_firings": {"sess-xyz": 1},
                                        "events": [
                                            {
                                                "task_id": "sess-xyz",
                                                "evidence": long_evidence,
                                            }
                                        ],
                                    }
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            data = current_taxonomy(workspace, BASE_STORE)
            first = data["codes"][0]
            self.assertEqual(first["task_firings"][0]["label"], "UID0001 ✓")
            event = first["runtime_evidence"][0]
            self.assertEqual(event["task_label"], "UID0001 ✓")
            self.assertEqual(event["evidence"], long_evidence)

    def test_clean_checkpoints_are_exposed_with_sequence_labels(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = ProgramWorkspace(root / "program")
            (workspace.root / ".atlas-task-labels.json").write_text(
                json.dumps({"task-clean": "Dataset item 7"}),
                encoding="utf-8",
            )
            (workspace.root / RUNTIME_EVIDENCE).write_text(
                json.dumps(
                    {
                        "version": 1,
                        "checkpoints": [
                            {
                                "taxonomy_id": "mast",
                                "checkpoint_id": "cp-fired",
                                "timestamp": 1,
                                "gate": "task_completed",
                                "task_id": "task-fired",
                                "fired_codes": ["MAST-1"],
                            },
                            {
                                "taxonomy_id": "mast",
                                "checkpoint_id": "cp-clean",
                                "timestamp": 2,
                                "gate": "stop",
                                "task_id": "task-clean",
                                "none_apply": True,
                                "considered_codes": ["MAST-1", "MAST-12"],
                                "fired_codes": [],
                                "observe": "everything relevant was checked",
                                "correlate": "no root failure found",
                                "decide": "no change needed, because checks passed",
                            },
                        ],
                        "taxonomies": {},
                    }
                ),
                encoding="utf-8",
            )

            data = current_taxonomy(workspace, BASE_STORE)

            self.assertEqual(len(data["clean_checkpoints"]), 1)
            clean = data["clean_checkpoints"][0]
            self.assertEqual(clean["seq"], 2)
            self.assertEqual(clean["checkpoint_id"], "cp-clean")
            self.assertEqual(clean["task_label"], "Dataset item 7")
            self.assertTrue(clean["none_apply"])
            self.assertEqual(clean["considered"], ["MAST-1", "MAST-12"])


class DashboardServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store_dir = self.root / "taxonomies"
        copy_store(self.store_dir)
        self.workspace = ProgramWorkspace(self.root / "program")
        self.workspace.bind_inherited_taxonomy(BASE_ID)
        self.server = build_server(
            self.workspace.root, self.store_dir, port=0
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.temp.cleanup()

    def _get(self, path: str) -> tuple[int, str, str]:
        with urlopen(f"http://127.0.0.1:{self.port}{path}") as response:
            return (
                response.status,
                response.headers["Content-Type"],
                response.read().decode("utf-8"),
            )

    def test_page_has_live_controls_and_optional_metric_renderer(self):
        status, content_type, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn("ATLAS / live taxonomy field manual", body)
        self.assertIn("Filter codes by id, name, or description", body)
        self.assertIn("Expand all", body)
        self.assertIn("Total firings", body)
        self.assertIn("task(s)", body)
        self.assertIn("Runtime evidence", body)
        self.assertIn("Clean checkpoints", body)
        self.assertNotIn("TASK-1042", body)

    def test_api_returns_render_ready_full_taxonomy(self):
        status, content_type, body = self._get("/api/taxonomy")
        self.assertEqual(status, 200)
        self.assertIn("application/json", content_type)
        data = json.loads(body)
        self.assertEqual(data["taxonomy_id"], BASE_ID)
        self.assertEqual(data["repo"], "django/django")
        self.assertEqual(data["codes"][0]["code_id"], "1")
        self.assertIn("N+1 query", data["codes"][0]["name"])
        self.assertIn("queryset", data["codes"][0]["description"])
        self.assertIsNone(data["codes"][0]["fire_count"])
        self.assertEqual(data["codes"][0]["task_firings"], [])
        self.assertEqual(data["codes"][0]["runtime_evidence"], [])
        self.assertEqual(data["clean_checkpoints"], [])

    def test_api_normalizes_optional_placeholder_metrics(self):
        record = json.loads(
            (self.store_dir / f"{BASE_ID}.json").read_text(encoding="utf-8")
        )
        record["codes"][0]["fire_count"] = 5
        record["codes"][0]["task_firings"] = [
            {"task_id": "TASK-A", "count": 2},
            {"task_id": "TASK-B", "count": 3},
        ]
        (self.store_dir / f"{BASE_ID}.json").write_text(
            json.dumps(record), encoding="utf-8"
        )
        _, _, body = self._get("/api/taxonomy")
        first = json.loads(body)["codes"][0]
        self.assertEqual(first["fire_count"], 5)
        self.assertEqual(
            first["task_firings"],
            [
                {"task_id": "TASK-A", "label": "TASK-A", "count": 2},
                {"task_id": "TASK-B", "label": "TASK-B", "count": 3},
            ],
        )

    def test_api_changes_without_server_restart(self):
        _, _, before_body = self._get("/api/taxonomy")
        original = json.loads(
            (self.store_dir / f"{BASE_ID}.json").read_text(encoding="utf-8")
        )
        successor = {**original, "taxonomy_id": NEXT_ID}
        (self.store_dir / f"{NEXT_ID}.json").write_text(
            json.dumps(successor), encoding="utf-8"
        )
        TaxonomyLineage(self.store_dir).add_successor(BASE_ID, NEXT_ID)
        _, _, after_body = self._get("/api/taxonomy")
        self.assertEqual(json.loads(before_body)["taxonomy_id"], BASE_ID)
        self.assertEqual(json.loads(after_body)["taxonomy_id"], NEXT_ID)

    def test_unknown_route_is_404(self):
        with self.assertRaises(HTTPError) as error:
            self._get("/missing")
        try:
            self.assertEqual(error.exception.code, 404)
        finally:
            error.exception.close()


class ManagedDashboardTests(unittest.TestCase):
    def test_start_reuse_and_stop(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = ProgramWorkspace(root / "program", repo="owner/project")
            with patch.dict(
                os.environ,
                {"ATLAS_DISABLE_DASHBOARD": ""},
            ):
                first = ensure_dashboard(workspace, BASE_STORE)
                self.assertTrue(first)
                second = ensure_dashboard(workspace, BASE_STORE)
                self.assertEqual(second, first)
                with urlopen(f"{first}api/health") as response:
                    health = json.loads(response.read().decode("utf-8"))
                self.assertEqual(health["program_id"], workspace.program_id)
                self.assertTrue(stop_dashboard(workspace))


if __name__ == "__main__":
    unittest.main()
