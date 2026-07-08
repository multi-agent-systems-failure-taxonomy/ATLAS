"""Shared adapter primitives used by hook integrations."""

from __future__ import annotations

from typing import Any


def build_session_state(
    *,
    session_id: str,
    session,
    cwd: str,
    max_retries: int,
    main_cursor: int,
    failure: dict[str, Any],
) -> dict[str, Any]:
    """Build the common persisted state envelope for hook adapters."""
    return {
        "version": 1,
        "session_id": session_id,
        "runtime_session_id": session.session_id,
        "program_id": session.program_id,
        "cwd": cwd,
        "taxonomy_id": session.delivery.taxonomy_id,
        "taxonomy": session.delivery.taxonomy,
        "dashboard_url": session.delivery.dashboard_url,
        "max_retries": max_retries,
        "lifecycle": {
            "store_dir": str(session.store_dir),
            "trace_root": str(session.trace_root),
            "generation_threshold": session.generation_threshold,
            "generation_stops": session.generation_stops,
            "skip_judge": session.skip_judge,
            "k_init": session.k_init,
            "k": session.k,
            "refinement_stops": session.refinement_stops,
            "advanced_refinement": session.advanced_refinement,
            "runtime_protocol": session.delivery.runtime_protocol,
        },
        "main_cursor": main_cursor,
        "pending": {},
        "failure": failure,
        "finished": False,
        "trace_captured": False,
    }
