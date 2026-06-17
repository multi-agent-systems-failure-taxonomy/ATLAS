"""Store tests, run against the REAL fixture records in taxonomies/."""

import unittest
from pathlib import Path

from finding import store

STORE_DIR = Path(__file__).resolve().parent.parent / "taxonomies"


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
        # full content: code number, failure-mode name, explanation present
        self.assertIn("code", first)
        self.assertIn("name", first)
        self.assertIn("explanation", first)

    def test_missing_raises(self):
        with self.assertRaises(store.TaxonomyNotFound):
            store.fetch_by_id("tax-does-not-exist", STORE_DIR)

    def test_exists(self):
        self.assertTrue(store.exists("tax-flask-routing-004", STORE_DIR))
        self.assertFalse(store.exists("tax-nope", STORE_DIR))


if __name__ == "__main__":
    unittest.main()
