"""Shared runtime-evidence recording for ATLAS integrations."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .fsio import read_text_retry, write_text_atomic_retry
from .reflection import ReflectionResult

EVIDENCE_FILE = ".atlas-runtime-evidence.json"


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
            data = json.loads(read_text_retry(path))
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
        write_text_atomic_retry(
            path,
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        )


@contextmanager
def _file_lock(path: Path, *, timeout: float = 5.0, stale_after: float = 30.0):
    lock = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir(parents=True)
            break
        except FileExistsError:
            # A writer killed mid-write leaves the lock directory behind
            # forever, silently disabling evidence recording for the whole
            # program. Break stale locks, mirroring locked_manifest().
            try:
                if time.time() - lock.stat().st_mtime > stale_after:
                    lock.rmdir()
                    continue
            except OSError:
                pass
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

