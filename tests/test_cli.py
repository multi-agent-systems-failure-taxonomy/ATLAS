"""CLI tests: end-to-end stdout/exit-code wiring for the three forms."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from finding import cli

STORE_DIR = str(Path(__file__).resolve().parent.parent / "taxonomies")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue().strip(), err.getvalue().strip()


class CliTests(unittest.TestCase):
    def test_no_inherit_prints_none(self):
        code, out, _ = run(["--store-dir", STORE_DIR])
        self.assertEqual(code, 0)
        self.assertEqual(out, "none")

    def test_explicit_existing_prints_id(self):
        code, out, _ = run(["--inherit", "tax-django-orm-001", "--store-dir", STORE_DIR])
        self.assertEqual(code, 0)
        self.assertEqual(out, "tax-django-orm-001")

    def test_explicit_missing_errors_nonzero(self):
        code, out, err = run(["--inherit", "tax-missing-999", "--store-dir", STORE_DIR])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")               # not a silent "none"
        self.assertIn("tax-missing-999", err)


if __name__ == "__main__":
    unittest.main()
