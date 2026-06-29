"""Persistent per-session hook state for the Codex integration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SESSION_DIR = ".atlas-codex"


def state_path(trace_output: Path, session_id: str) -> Path:
    safe = "".join(
        char if char.isalnum() or char in "._-" else "_"
        for char in session_id
    )
    return trace_output / SESSION_DIR / f"{safe}.json"


def load_state(trace_output: Path, session_id: str) -> dict[str, Any]:
    path = state_path(trace_output, session_id)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(trace_output: Path, session_id: str, state: dict[str, Any]) -> None:
    path = state_path(trace_output, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
