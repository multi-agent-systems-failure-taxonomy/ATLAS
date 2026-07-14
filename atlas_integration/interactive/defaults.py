"""Defaults shared by interactive Codex and Claude Code installations."""

from __future__ import annotations

from pathlib import Path

INTERACTIVE_ATLAS_MODEL = "interactive-session"


def default_interactive_trace_output(home: Path | None = None) -> Path:
    """Return the shared project-scoped store used by user-level hooks."""
    return (home or Path.home()) / ".atlas-skill" / "interactive"
