"""Health-check CLI tests."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from atlas_runtime.doctor import ERROR, WARN, has_errors, run_checks


class DoctorCheckTests(unittest.TestCase):
    def test_basic_checks_pass_with_temp_storage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checks = run_checks(
                store_dir=root / "taxonomies",
                trace_root=root / "traces",
                trace_output=root / "program",
                atlas_model="gpt-5",
            )
        by_name = {check.name: check for check in checks}
        self.assertEqual(by_name["python"].status, "ok")
        self.assertEqual(by_name["taxonomy store"].status, "ok")
        self.assertEqual(by_name["trace root"].status, "ok")
        self.assertEqual(by_name["trace output"].status, "ok")
        self.assertEqual(by_name["atlas model"].status, "ok")
        self.assertFalse(has_errors(checks))

    def test_missing_model_is_warning_not_error(self):
        with tempfile.TemporaryDirectory() as td:
            checks = run_checks(
                store_dir=Path(td) / "taxonomies",
                trace_root=Path(td) / "traces",
            )
        self.assertEqual(
            [check.status for check in checks if check.name == "atlas model"],
            [WARN],
        )
        self.assertFalse(has_errors(checks))

    def test_unrecognized_model_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            checks = run_checks(
                store_dir=Path(td) / "taxonomies",
                trace_root=Path(td) / "traces",
                atlas_model="totally-not-a-real-model",
            )
        self.assertEqual(
            [check.status for check in checks if check.name == "atlas model"],
            [ERROR],
        )
        self.assertTrue(has_errors(checks))

    def test_json_cli_exits_zero_for_warnings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "atlas_runtime.doctor",
                    "--store-dir",
                    str(root / "taxonomies"),
                    "--trace-root",
                    str(root / "traces"),
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(any(item["name"] == "atlas model" for item in payload))

    def test_invalid_dashboard_port_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "atlas_runtime.doctor",
                    "--store-dir",
                    str(root / "taxonomies"),
                    "--trace-root",
                    str(root / "traces"),
                    "--dashboard-port",
                    "70000",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("dashboard port", proc.stdout)

    def test_dashboard_port_zero_means_ephemeral_port_check(self):
        with tempfile.TemporaryDirectory() as td:
            checks = run_checks(
                store_dir=Path(td) / "taxonomies",
                trace_root=Path(td) / "traces",
                dashboard_port=0,
            )
        dashboard = [check for check in checks if check.name == "dashboard port"]
        self.assertEqual(dashboard[0].status, "ok")


if __name__ == "__main__":
    unittest.main()
