"""Persistent per-session hook state and live runtime evidence."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .reflection import ReflectionResult

SESSION_DIR = ".atlas-claude-code"
EVIDENCE_FILE = ".atlas-runtime-evidence.json"


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


def record_reflection(
    trace_output: Path,
    state: dict[str, Any],
    reflection: ReflectionResult,
    *,
    gate: str,
    task_id: str,
    agent_id: str | None = None,
    agent_type: str | None = None,
) -> None:
    """Atomically append fired-code evidence scoped to one taxonomy ID."""
    path = trace_output / EVIDENCE_FILE
    with _file_lock(path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {"version": 1, "taxonomies": {}, "checkpoints": []}
        taxonomy_id = str(state["taxonomy_id"])
        taxonomy = data.setdefault("taxonomies", {}).setdefault(
            taxonomy_id, {"codes": {}}
        )
        timestamp = time.time()
        event_base = {
            "checkpoint_id": reflection.checkpoint_id,
            "gate": gate,
            "task_id": task_id,
            "session_id": state["session_id"],
            "agent_id": agent_id,
            "agent_type": agent_type,
            "observe": reflection.observe,
            "correlate": reflection.correlate,
            "decide": reflection.decide,
            "timestamp": timestamp,
        }
        for assignment in reflection.assignments:
            code = taxonomy.setdefault("codes", {}).setdefault(
                assignment.code_id,
                {"fire_count": 0, "task_firings": {}, "events": []},
            )
            code["fire_count"] = int(code.get("fire_count", 0)) + 1
            firings = code.setdefault("task_firings", {})
            firings[task_id] = int(firings.get(task_id, 0)) + 1
            code.setdefault("events", []).append(
                {**event_base, "evidence": assignment.evidence}
            )
        data.setdefault("checkpoints", []).append(
            {
                **event_base,
                "taxonomy_id": taxonomy_id,
                "none_apply": reflection.none_apply,
                "considered_codes": list(reflection.considered_codes),
                "fired_codes": [
                    assignment.code_id
                    for assignment in reflection.assignments
                ],
            }
        )
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)


@contextmanager
def _file_lock(path: Path, *, timeout: float = 5.0):
    lock = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir(parents=True)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for {lock}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except FileNotFoundError:
            pass
