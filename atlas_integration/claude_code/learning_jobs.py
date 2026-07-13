"""Claude Code adapter for the shared durable taxonomy job coordinator."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable

from atlas_runtime import ProgramWorkspace

from atlas_integration.codex.learning_jobs import (
    LearningJobError,
    drain_learning_notices,
    enqueue_learning_job,
    reconcile_learning_jobs,
)


def resolve_claude_cli(explicit: Path | str | None = None) -> Path:
    """Locate Claude Code without reading or copying its credentials."""
    candidates = [
        str(explicit) if explicit else None,
        os.environ.get("CLAUDE_CLI_PATH"),
        shutil.which("claude.cmd"),
        shutil.which("claude"),
        str(Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd")
        if os.environ.get("APPDATA")
        else None,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser().resolve()
        if path.is_file():
            return path
    raise LearningJobError(
        "Claude Code CLI was not found; set claude_code.claude_cli_path"
    )


def enqueue_claude_learning_job(
    workspace: ProgramWorkspace,
    *,
    kind: str,
    store_dir: Path | str,
    trace_root: Path | str,
    task_group: str,
    conversation_id: str,
    worker_model: str | None = None,
    claude_cli_path: Path | str | None = None,
    worker_timeout_seconds: int = 1800,
    launcher: Callable[[Path], None] | None = None,
) -> str:
    resolved_cli = resolve_claude_cli(claude_cli_path)
    return enqueue_learning_job(
        workspace,
        kind=kind,
        store_dir=store_dir,
        trace_root=trace_root,
        task_group=task_group,
        conversation_id=conversation_id,
        worker_model=worker_model,
        worker_cli_path=resolved_cli,
        worker_timeout_seconds=worker_timeout_seconds,
        worker_driver="claude_subagent",
        worker_label="Claude Code taxonomy subagent",
        worker_module="atlas_integration.claude_code.native_worker",
        job_prefix="claude",
        launcher=launcher,
    )


__all__ = [
    "LearningJobError",
    "drain_learning_notices",
    "enqueue_claude_learning_job",
    "reconcile_learning_jobs",
    "resolve_claude_cli",
]
