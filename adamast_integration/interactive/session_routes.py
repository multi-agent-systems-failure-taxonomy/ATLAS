"""Host-neutral conversation scope and fresh taxonomy branch routing."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adamast_runtime.fsio import read_text_retry, write_text_atomic_retry
from adamast_runtime.project_scope import project_program_path, validate_scope_id


@dataclass(frozen=True)
class SessionRoute:
    task_group: str
    trace_output: Path


def event_session_id(event: dict[str, Any]) -> str:
    for key in ("session_id", "thread_id", "conversation_id"):
        value = event.get(key)
        if value:
            return str(value)
    return str(event.get("transcript_path") or "").strip()


def resolve_conversation_scope(
    routing_root: Path,
    event: dict[str, Any],
    *,
    default_trace_output: Path,
    default_task_group: str,
    scope_dir: str,
    state_dir: str,
    host_label: str,
) -> SessionRoute | None:
    """Pin one host conversation to one program despite later cwd drift.

    Interactive hosts report their current working directory on every event.
    Resuming a conversation after ``cd``-ing (or from a different shell) must
    not turn that existing conversation into a new AdaMAST session.  Existing
    installations are migrated by locating an already selected state before
    the binding is written.
    """
    session_id = event_session_id(event)
    if not session_id:
        return None
    root = Path(routing_root).expanduser().resolve()
    path = _conversation_scope_path(root, session_id, scope_dir=scope_dir)
    resolved = _read_scope_record(path, root)
    if resolved:
        return resolved

    migrated = _discover_selected_scope(
        root,
        session_id,
        state_dir=state_dir,
        default_task_group=default_task_group,
    )
    target = migrated or SessionRoute(
        task_group=validate_scope_id(
            default_task_group,
            label="task_group",
        ),
        trace_output=Path(default_trace_output).expanduser().resolve(),
    )
    if not _is_within(target.trace_output, root):
        raise ValueError(
            f"{host_label} conversation scope must remain inside the AdaMAST "
            f"routing root: {target.trace_output}"
        )
    record = {
        "version": 1,
        "session_id": session_id,
        "task_group": target.task_group,
        "trace_output": str(target.trace_output),
        "bound_cwd": str(event.get("cwd") or ""),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic_retry(
        path,
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
    )
    return target


def resolve_session_route(
    routing_root: Path,
    event: dict[str, Any],
    *,
    default_trace_output: Path,
    route_dir: str,
) -> SessionRoute | None:
    """Load a route only when it belongs to this conversation and scope."""
    session_id = event_session_id(event)
    if not session_id:
        return None
    path = _route_path(
        routing_root,
        session_id,
        default_trace_output,
        route_dir=route_dir,
    )
    try:
        record = json.loads(read_text_retry(path))
    except (OSError, json.JSONDecodeError):
        return None
    if record.get("version") != 1:
        return None
    if record.get("default_scope") != _scope_fingerprint(default_trace_output):
        return None
    try:
        task_group = validate_scope_id(
            str(record.get("task_group") or ""),
            label="task_group",
        )
        trace_output = Path(str(record["trace_output"])).expanduser().resolve()
    except (KeyError, TypeError, ValueError, OSError):
        return None
    if not _is_within(trace_output, routing_root):
        return None
    return SessionRoute(task_group=task_group, trace_output=trace_output)


def create_fresh_session_route(
    routing_root: Path,
    event: dict[str, Any],
    *,
    default_trace_output: Path,
    project_scope: str,
    project_id: str | None,
    route_dir: str,
    fresh_dir: str,
    host_label: str,
) -> SessionRoute:
    """Create an idempotent MAST-from-zero route for one conversation."""
    session_id = event_session_id(event)
    if not session_id:
        raise ValueError(f"a {host_label} conversation id is required to start fresh")
    existing = resolve_session_route(
        routing_root,
        event,
        default_trace_output=default_trace_output,
        route_dir=route_dir,
    )
    if existing:
        return existing

    digest = hashlib.sha256(
        f"{session_id}\0{_normalized(default_trace_output)}".encode(
            "utf-8", "replace"
        )
    ).hexdigest()[:12]
    task_group = f"fresh-{digest}"
    validate_scope_id(task_group, label="task_group")
    root = Path(routing_root).expanduser().resolve()
    if project_scope == "auto":
        trace_output = project_program_path(
            root,
            cwd=event.get("cwd"),
            task_group=task_group,
            project_id=project_id,
        )
    else:
        trace_output = root / fresh_dir / task_group / "program"
    record = {
        "version": 1,
        "default_scope": _scope_fingerprint(default_trace_output),
        "task_group": task_group,
        "trace_output": str(trace_output),
        "mode": "mast_fresh",
    }
    path = _route_path(
        root,
        session_id,
        default_trace_output,
        route_dir=route_dir,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic_retry(
        path,
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
    )
    return SessionRoute(task_group=task_group, trace_output=trace_output)


def _route_path(
    routing_root: Path,
    session_id: str,
    default_trace_output: Path,
    *,
    route_dir: str,
) -> Path:
    digest = hashlib.sha256(
        f"{session_id}\0{_normalized(default_trace_output)}".encode(
            "utf-8", "replace"
        )
    ).hexdigest()
    return Path(routing_root).expanduser().resolve() / route_dir / f"{digest}.json"


def _conversation_scope_path(
    routing_root: Path,
    session_id: str,
    *,
    scope_dir: str,
) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8", "replace")).hexdigest()
    return Path(routing_root).expanduser().resolve() / scope_dir / f"{digest}.json"


def _read_scope_record(path: Path, routing_root: Path) -> SessionRoute | None:
    try:
        record = json.loads(read_text_retry(path))
    except (OSError, json.JSONDecodeError):
        return None
    if record.get("version") != 1:
        return None
    try:
        task_group = validate_scope_id(
            str(record.get("task_group") or ""),
            label="task_group",
        )
        trace_output = Path(str(record["trace_output"])).expanduser().resolve()
    except (KeyError, TypeError, ValueError, OSError):
        return None
    if not _is_within(trace_output, routing_root):
        return None
    return SessionRoute(task_group=task_group, trace_output=trace_output)


def _discover_selected_scope(
    routing_root: Path,
    session_id: str,
    *,
    state_dir: str,
    default_task_group: str,
) -> SessionRoute | None:
    safe_id = "".join(
        char if char.isalnum() or char in "._-" else "_"
        for char in session_id
    )
    candidates: list[tuple[int, int, SessionRoute]] = []
    for path in routing_root.rglob(f"{safe_id}.json"):
        if path.parent.name != state_dir:
            continue
        try:
            state = json.loads(read_text_retry(path))
            status = str((state.get("selection") or {}).get("status") or "")
            if status not in {"selected", "disabled"}:
                continue
            trace_output = path.parent.parent.resolve()
            if not _is_within(trace_output, routing_root):
                continue
            task_group = _task_group_from_program(
                trace_output,
                default=default_task_group,
            )
            sequence = int(state.get("episode_sequence") or 0)
            modified = path.stat().st_mtime_ns
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        candidates.append(
            (
                sequence,
                modified,
                SessionRoute(task_group=task_group, trace_output=trace_output),
            )
        )
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _task_group_from_program(path: Path, *, default: str) -> str:
    parent = Path(path).parent
    if parent.parent.name == "groups":
        try:
            return validate_scope_id(parent.name, label="task_group")
        except ValueError:
            pass
    return validate_scope_id(default, label="task_group")


def _scope_fingerprint(path: Path) -> str:
    return hashlib.sha256(
        _normalized(path).encode("utf-8", "replace")
    ).hexdigest()


def _normalized(path: Path) -> str:
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(parent).expanduser().resolve())
        return True
    except ValueError:
        return False
