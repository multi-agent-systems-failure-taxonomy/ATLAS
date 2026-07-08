"""General, agent- and model-agnostic ATLAS runtime framework."""

from __future__ import annotations

from typing import Any, Callable, Mapping


# ── Shared callable type contracts ──────────────────────────────────────
#
# Every entry point that exposes a ``project_fn`` (oracle-blind trace
# projection) MUST use this type, so callers can write a single function
# usable across generation, refinement, and registration without hitting
# silent shape mismatches between modules. The convention: a project_fn
# takes a trace dict (the canonical ATLAS trace record) and returns a
# dict (possibly the same one, possibly a rewritten copy). String-only
# variants are explicitly disallowed; if you need to rewrite only the
# raw_trajectory text, do it inside the dict and return the mutated dict.
ProjectFn = Callable[[Mapping[str, Any]], Mapping[str, Any]]


from .lifecycle import (
    Session,
    SessionDelivery,
    SessionEndResult,
    end_session,
    pre_submission,
    record_trace,
    start_session,
)
from .config import load_atlas_config
from .protocol import GateDecision, evaluate_pre_submission, render_protocol
from .generation import GenerationResult
from .program import ProgramConflict, ProgramWorkspace
from .options import RuntimeOptions, add_runtime_arguments, parse_runtime_args
from .refinement import RefinementResult
from .checkpoint_prompt import render_reflection_prompt
from .evidence import EVIDENCE_FILE, record_reflection
from .reflection import CodeAssignment, ReflectionResult, parse_reflection
from .dashboard import (
    build_server as build_dashboard_server,
    current_taxonomy,
    ensure_dashboard,
    stop_dashboard,
    stop_dashboard_if_idle,
)
from .repository import discover_repo
from .redaction import redact_text, redact_trace
from .traces import (
    GenerationTrace,
    RetentionPolicy,
    RetentionReport,
    TraceStore,
)
from .status import program_health

__all__ = [
    "GateDecision",
    "GenerationResult",
    "GenerationTrace",
    "CodeAssignment",
    "EVIDENCE_FILE",
    "ProgramConflict",
    "ProgramWorkspace",
    "ProjectFn",
    "ReflectionResult",
    "RuntimeOptions",
    "RetentionPolicy",
    "RetentionReport",
    "RefinementResult",
    "build_dashboard_server",
    "current_taxonomy",
    "discover_repo",
    "ensure_dashboard",
    "Session",
    "SessionDelivery",
    "SessionEndResult",
    "TraceStore",
    "end_session",
    "evaluate_pre_submission",
    "pre_submission",
    "record_trace",
    "record_reflection",
    "render_protocol",
    "render_reflection_prompt",
    "load_atlas_config",
    "parse_reflection",
    "program_health",
    "redact_text",
    "redact_trace",
    "start_session",
    "stop_dashboard",
    "stop_dashboard_if_idle",
    "add_runtime_arguments",
    "parse_runtime_args",
]
