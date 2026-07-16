"""Claude Code facade for the shared native taxonomy receipt protocol."""

from __future__ import annotations

from typing import Any

from adamast_integration.interactive.subagent_protocol import (
    MAX_RECEIPT_CHARS,
    RECEIPT_CLOSE,
    RECEIPT_OPEN,
    capture_learning_receipt,
    complete_learning_job,
    complete_support_review,
    fail_learning_job,
)
from adamast_integration.interactive.subagent_protocol import (
    claim_learning_job as _claim_learning_job,
)
from adamast_runtime import ProgramWorkspace


def claim_learning_job(
    workspace: ProgramWorkspace,
    *,
    conversation_id: str,
    lease_seconds: int = 1800,
) -> dict[str, Any] | None:
    """Claim one job and render instructions for Claude Code's Agent tool."""
    return _claim_learning_job(
        workspace,
        conversation_id=conversation_id,
        lease_seconds=lease_seconds,
        host_label="Claude Code",
        subagent_capability="Claude Code's native Agent tool",
        forbidden_cli="claude -p or a standalone Claude process",
    )


__all__ = [
    "MAX_RECEIPT_CHARS",
    "RECEIPT_CLOSE",
    "RECEIPT_OPEN",
    "capture_learning_receipt",
    "claim_learning_job",
    "complete_learning_job",
    "complete_support_review",
    "fail_learning_job",
]
