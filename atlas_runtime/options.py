"""Reusable command-line options for any agent or model integration."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class RuntimeOptions:
    trace_output: Path
    atlas_model: str
    repo: str | None = None
    repo_path: Path | None = None
    generation_stops: bool = False
    refinement_stops: bool = False
    advanced_refinement: bool = False
    taxonomy_check: bool = True


def add_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--trace-output",
        "--trace_output",
        dest="trace_output",
        type=Path,
        required=True,
        help="program-specific ATLAS trace directory (required for every run)",
    )
    parser.add_argument(
        "--atlas-model",
        "--atlas_model",
        dest="atlas_model",
        required=True,
        help="recognized model shared by ATLAS generation, judging, and refinement",
    )
    parser.add_argument(
        "--repo",
        help="display-only repository label; never used for taxonomy routing",
    )
    parser.add_argument(
        "--repo-path",
        "--repo_path",
        dest="repo_path",
        type=Path,
        help="path used to derive display-only repository metadata",
    )
    parser.add_argument(
        "--taxonomy-check",
        "--taxonomy_check",
        dest="taxonomy_check",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="judge generated taxonomies before acceptance (default: true)",
    )
    parser.add_argument(
        "--refinement-stops",
        "--refinement_stops",
        dest="refinement_stops",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "wait at task completion for taxonomy refinement; default is "
            "non-blocking"
        ),
    )
    parser.add_argument(
        "--advanced-refinement",
        "--advanced_refinement",
        dest="advanced_refinement",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="run one support-judge pass and at most one repair during refinement",
    )
    parser.add_argument(
        "--generation-stops",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "wait at task completion for taxonomy generation; default is "
            "non-blocking"
        ),
    )


def parse_runtime_args(args: Sequence[str]) -> RuntimeOptions:
    parser = argparse.ArgumentParser(add_help=False)
    add_runtime_arguments(parser)
    parsed = parser.parse_args(args)
    return RuntimeOptions(
        trace_output=parsed.trace_output,
        atlas_model=parsed.atlas_model,
        repo=parsed.repo,
        repo_path=parsed.repo_path,
        generation_stops=parsed.generation_stops,
        refinement_stops=parsed.refinement_stops,
        advanced_refinement=parsed.advanced_refinement,
        taxonomy_check=parsed.taxonomy_check,
    )
