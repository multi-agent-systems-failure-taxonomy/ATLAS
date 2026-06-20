"""General, agent- and model-agnostic ATLAS runtime framework."""

from .lifecycle import (
    Session,
    SessionDelivery,
    SessionEndResult,
    end_session,
    pre_submission,
    record_trace,
    start_session,
)
from .protocol import GateDecision, evaluate_pre_submission, render_protocol
from .generation import GenerationResult
from .program import ProgramConflict, ProgramWorkspace
from .options import RuntimeOptions, add_runtime_arguments, parse_runtime_args
from .refinement import RefinementResult
from .dashboard import (
    build_server as build_dashboard_server,
    current_taxonomy,
    ensure_dashboard,
    stop_dashboard,
    stop_dashboard_if_idle,
)
from .repository import discover_repo
from .traces import (
    GenerationTrace,
    RetentionPolicy,
    RetentionReport,
    TraceStore,
)

__all__ = [
    "GateDecision",
    "GenerationResult",
    "GenerationTrace",
    "ProgramConflict",
    "ProgramWorkspace",
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
    "render_protocol",
    "start_session",
    "stop_dashboard",
    "stop_dashboard_if_idle",
    "add_runtime_arguments",
    "parse_runtime_args",
]
