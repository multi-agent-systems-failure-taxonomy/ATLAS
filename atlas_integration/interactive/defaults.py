"""Defaults shared by interactive Codex and Claude Code installations."""

from __future__ import annotations

from pathlib import Path

from atlas_runtime.program import INTERACTIVE_SESSION_MODEL

# Re-exported alias: the runtime owns the sentinel because begin_session
# must recognize it when reconciling against recorded program state.
INTERACTIVE_ATLAS_MODEL = INTERACTIVE_SESSION_MODEL


def default_interactive_trace_output(home: Path | None = None) -> Path:
    """Return the shared project-scoped store used by user-level hooks."""
    return (home or Path.home()) / ".atlas-skill" / "interactive"
