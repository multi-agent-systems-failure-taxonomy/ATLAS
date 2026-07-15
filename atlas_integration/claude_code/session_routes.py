"""Claude Code facade for shared durable interactive session routing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atlas_integration.interactive.session_routes import (
    SessionRoute,
    event_session_id,
)
from atlas_integration.interactive.session_routes import (
    create_fresh_session_route as _create_fresh_session_route,
)
from atlas_integration.interactive.session_routes import (
    resolve_session_route as _resolve_session_route,
)

ROUTE_DIR = ".atlas-claude-routes"
FRESH_DIR = ".atlas-claude-fresh"


def resolve_session_route(
    routing_root: Path,
    event: dict[str, Any],
    *,
    default_trace_output: Path,
) -> SessionRoute | None:
    return _resolve_session_route(
        routing_root,
        event,
        default_trace_output=default_trace_output,
        route_dir=ROUTE_DIR,
    )


def create_fresh_session_route(
    routing_root: Path,
    event: dict[str, Any],
    *,
    default_trace_output: Path,
    project_scope: str,
    project_id: str | None,
) -> SessionRoute:
    return _create_fresh_session_route(
        routing_root,
        event,
        default_trace_output=default_trace_output,
        project_scope=project_scope,
        project_id=project_id,
        route_dir=ROUTE_DIR,
        fresh_dir=FRESH_DIR,
        host_label="Claude Code",
    )


__all__ = [
    "FRESH_DIR",
    "ROUTE_DIR",
    "SessionRoute",
    "create_fresh_session_route",
    "event_session_id",
    "resolve_session_route",
]
