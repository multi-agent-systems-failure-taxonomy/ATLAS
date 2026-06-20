"""Reusable runtime CLI option tests."""

import unittest

from atlas_runtime.options import parse_runtime_args


class RuntimeOptionTests(unittest.TestCase):
    def test_trace_output_is_required(self):
        with self.assertRaises(SystemExit):
            parse_runtime_args([])

    def test_generation_stops_defaults_false(self):
        options = parse_runtime_args(
            ["--trace-output", "./program", "--atlas-model", "claude-sonnet-4-6"]
        )
        self.assertFalse(options.generation_stops)
        self.assertFalse(options.refinement_stops)
        self.assertFalse(options.advanced_refinement)
        self.assertTrue(options.taxonomy_check)

    def test_generation_stops_can_be_enabled(self):
        options = parse_runtime_args(
            ["--trace-output", "./program", "--generation-stops"]
            + ["--atlas-model", "claude-sonnet-4-6"]
        )
        self.assertTrue(options.generation_stops)

    def test_underscore_trace_output_alias(self):
        options = parse_runtime_args(
            ["--trace_output", "./program", "--atlas_model", "claude-sonnet-4-6"]
        )
        self.assertEqual(options.trace_output.name, "program")

    def test_refinement_stops_and_underscore_alias(self):
        dashed = parse_runtime_args(
            ["--trace-output", "./program", "--atlas-model", "claude-sonnet-4-6",
             "--refinement-stops"]
        )
        underscored = parse_runtime_args(
            ["--trace-output", "./program", "--atlas-model", "claude-sonnet-4-6",
             "--refinement_stops"]
        )
        self.assertTrue(dashed.refinement_stops)
        self.assertTrue(underscored.refinement_stops)

    def test_taxonomy_check_can_be_disabled(self):
        options = parse_runtime_args(
            ["--trace-output", "./program", "--atlas-model", "claude-sonnet-4-6",
             "--no-taxonomy-check"]
        )
        self.assertFalse(options.taxonomy_check)
        self.assertEqual(options.atlas_model, "claude-sonnet-4-6")

    def test_advanced_refinement_and_underscore_alias(self):
        dashed = parse_runtime_args(
            ["--trace-output", "./program", "--atlas-model", "claude-sonnet-4-6",
             "--advanced-refinement"]
        )
        underscored = parse_runtime_args(
            ["--trace-output", "./program", "--atlas-model", "claude-sonnet-4-6",
             "--advanced_refinement"]
        )
        self.assertTrue(dashed.advanced_refinement)
        self.assertTrue(underscored.advanced_refinement)

    def test_repository_metadata_options(self):
        options = parse_runtime_args(
            [
                "--trace-output", "./program",
                "--atlas-model", "claude-sonnet-4-6",
                "--repo", "owner/project",
                "--repo-path", "./checkout",
            ]
        )
        self.assertEqual(options.repo, "owner/project")
        self.assertEqual(options.repo_path.name, "checkout")


if __name__ == "__main__":
    unittest.main()
