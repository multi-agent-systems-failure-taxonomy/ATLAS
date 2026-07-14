"""Shared adapter primitives used by hook integrations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, data: dict) -> None:
    """Write JSON via a same-directory temp file and atomic replace.

    Settings files (including the user's global Claude settings) must never
    be left half-written by an interrupted process.
    """
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def build_session_state(
    *,
    session_id: str,
    session,
    cwd: str,
    max_retries: int,
    main_cursor: int,
    failure: dict[str, Any],
    episode_sequence: int = 1,
    episode_cursor: int | None = None,
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
            "freeze": session.freeze,
            "evidence_export": (
                str(session.evidence_export) if session.evidence_export else None
            ),
            "runtime_protocol": session.delivery.runtime_protocol,
        },
        "main_cursor": main_cursor,
        "episode_sequence": episode_sequence,
        "episode_cursor": (
            main_cursor if episode_cursor is None else episode_cursor
        ),
        "pending": {},
        "failure": failure,
        "finished": False,
        "trace_captured": False,
    }
