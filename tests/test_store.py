"""Store tests, run against the REAL fixture records in tests/fixtures/taxonomies/."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from finding import store

STORE_DIR = Path(__file__).resolve().parent / "fixtures" / "taxonomies"


class DefaultPathTests(unittest.TestCase):
    def test_atlas_home_controls_writable_store_and_trace_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "atlas-home"
            env = os.environ.copy()
            env["ATLAS_HOME"] = str(root)
            env.pop("ATLAS_STORE_DIR", None)
            env.pop("ATLAS_TRACE_ROOT", None)
            env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
            output = subprocess.check_output(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json; from finding.store import DEFAULT_STORE_DIR; "
                        "from atlas_runtime.traces import DEFAULT_TRACE_ROOT; "
                        "print(json.dumps([str(DEFAULT_STORE_DIR), "
                        "str(DEFAULT_TRACE_ROOT)]))"
                    ),
                ],
                text=True,
                env=env,
            )
            store_path, trace_path = json.loads(output)
            self.assertEqual(Path(store_path), root / "taxonomies")
            self.assertEqual(Path(trace_path), root / "traces")


class ListAllTests(unittest.TestCase):
    def test_reads_only_the_three_header_fields(self):
        records = store.list_all(STORE_DIR)
        self.assertTrue(records, "fixtures should not be empty")
        for rec in records:
            self.assertEqual(set(rec.keys()), {"taxonomy_id", "repo", "domain"})

    def test_is_global_across_repos(self):
        repos = {rec["repo"] for rec in store.list_all(STORE_DIR)}
        # fixtures intentionally span multiple repos; list_all does not partition
        self.assertGreater(len(repos), 1)

    def test_contains_known_fixture(self):
        ids = {rec["taxonomy_id"] for rec in store.list_all(STORE_DIR)}
        self.assertIn("tax-django-orm-001", ids)


class FetchByIdTests(unittest.TestCase):
    def test_returns_full_record(self):
        rec = store.fetch_by_id("tax-numpy-array-003", STORE_DIR)
        self.assertEqual(rec["taxonomy_id"], "tax-numpy-array-003")
        self.assertEqual(rec["repo"], "numpy/numpy")
        self.assertEqual(rec["domain"], "numerical-computing")
        self.assertGreaterEqual(len(rec["codes"]), 1)
        first = rec["codes"][0]
        # full content: the canonical code schema (id/name/description/category)
        self.assertIn("id", first)
        self.assertIn("name", first)
        self.assertIn("description", first)
        self.assertIn("category", first)

    def test_missing_raises(self):
        with self.assertRaises(store.TaxonomyNotFound):
            store.fetch_by_id("tax-does-not-exist", STORE_DIR)

    def test_exists(self):
        self.assertTrue(store.exists("tax-flask-routing-004", STORE_DIR))
        self.assertFalse(store.exists("tax-nope", STORE_DIR))


class RegisterTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads(
            (STORE_DIR / "tax-django-orm-001.json").read_text(encoding="utf-8")
        )
        self.record["taxonomy_id"] = "tax-registered-test"

    def test_register_writes_new_format_and_makes_it_available(self):
        with tempfile.TemporaryDirectory() as td:
            path = store.register(self.record, td)
            self.assertEqual(path.name, "tax-registered-test.json")
            self.assertEqual(
                store.fetch_by_id("tax-registered-test", td),
                self.record,
            )
            self.assertIn(
                "tax-registered-test",
                {row["taxonomy_id"] for row in store.list_all(td)},
            )

    def test_duplicate_requires_explicit_replace(self):
        with tempfile.TemporaryDirectory() as td:
            store.register(self.record, td)
            with self.assertRaises(store.TaxonomyAlreadyExists):
                store.register(self.record, td)
            replacement = {**self.record, "domain": "replacement-domain"}
            store.register(replacement, td, replace=True)
            self.assertEqual(
                store.fetch_by_id("tax-registered-test", td)["domain"],
                "replacement-domain",
            )

    def test_rejects_unsafe_or_reserved_ids(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(store.InvalidTaxonomy):
                store.register({**self.record, "taxonomy_id": "../escape"}, td)
            with self.assertRaises(store.InvalidTaxonomy):
                store.register({**self.record, "taxonomy_id": "mast"}, td)

    def test_rejects_missing_schema_fields(self):
        with tempfile.TemporaryDirectory() as td:
            invalid = dict(self.record)
            del invalid["codes"]
            with self.assertRaises(store.InvalidTaxonomy):
                store.register(invalid, td)

    def test_rejects_malformed_code(self):
        with tempfile.TemporaryDirectory() as td:
            # missing a canonical field (category)
            missing_category = {
                **self.record,
                "codes": [{"id": "1", "name": "n", "description": "d"}],
            }
            with self.assertRaises(store.InvalidTaxonomy):
                store.register(missing_category, td)

            # canonical field present but empty
            empty_name = {
                **self.record,
                "codes": [
                    {"id": "1", "name": "   ", "description": "d", "category": "Cat"}
                ],
            }
            with self.assertRaises(store.InvalidTaxonomy):
                store.register(empty_name, td)

            # the dead pre-canonical shape (code/explanation) is rejected outright
            legacy_shape = {
                **self.record,
                "codes": [{"code": 1, "name": "n", "explanation": "e"}],
            }
            with self.assertRaises(store.InvalidTaxonomy):
                store.register(legacy_shape, td)


if __name__ == "__main__":
    unittest.main()
