"""The minimal pre-submission ATLAS protocol.

This is deliberately narrower than the earlier ATLAS protocol: there are no
mid-task checkpoints, reflection workflow, task routing fields, or maturity
rules. The active taxonomy is consulted only at the pre-submission gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

READY = "READY_TO_SUBMIT"
REPAIR = "REPAIR_REQUIRED"

_STATUS_RE = re.compile(
    r"Final\s+ATLAS\s+status\s*:\s*(READY_TO_SUBMIT|REPAIR_REQUIRED)",
    re.IGNORECASE,
)
_ATTEMPTS_RE = re.compile(
    r"Repair\s+attempts\s+used\s*:\s*(\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GateDecision:
    """Agent- and model-agnostic verdict returned to the caller."""

    allow: bool
    decision: str
    reason: str
    status: str | None
    repair_attempts_used: int


def render_protocol(max_retries: int = 3) -> str:
    """Return the runtime text delivered beside the selected taxonomy."""
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    return f"""# ATLAS pre-submission gate

Before declaring the task complete, compare the full task trajectory and
verification evidence against the active failure-mode taxonomy.

Return one of:

- `READY_TO_SUBMIT` when no unresolved taxonomy-relevant issue remains.
- `REPAIR_REQUIRED` when one or more issues remain.

If repair is required, address the highest-impact unresolved issue, verify the
repair, and run this gate again. Perform at most {max_retries} repair attempts.
After {max_retries} unsuccessful attempts, stop repairing and report the
remaining issue honestly instead of claiming clean success.

Final gate format:

- `Final ATLAS status:` READY_TO_SUBMIT | REPAIR_REQUIRED
- `Codes checked:` relevant taxonomy ids, or none
- `Evidence:` concrete task or verification evidence
- `Repair attempts used:` 0-{max_retries}
- `Final decision:` submit | repair | report unresolved
"""


def evaluate_pre_submission(
    gate_text: str,
    *,
    max_retries: int = 3,
) -> GateDecision:
    """Classify the latest final-gate block.

    Missing/invalid gate text blocks. REPAIR_REQUIRED blocks while retry budget
    remains, then allows an honest unresolved report once the cap is reached.
    """
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")

    statuses = _STATUS_RE.findall(gate_text or "")
    attempts = _ATTEMPTS_RE.findall(gate_text or "")
    if not statuses:
        return GateDecision(
            allow=False,
            decision="block",
            reason="missing `Final ATLAS status:` block",
            status=None,
            repair_attempts_used=0,
        )

    status = statuses[-1].upper()
    used = int(attempts[-1]) if attempts else 0

    if status == READY:
        return GateDecision(
            allow=True,
            decision="approve",
            reason="pre-submission gate is ready",
            status=READY,
            repair_attempts_used=used,
        )

    if used < max_retries:
        return GateDecision(
            allow=False,
            decision="block",
            reason=f"repair required; {max_retries - used} attempt(s) remain",
            status=REPAIR,
            repair_attempts_used=used,
        )

    return GateDecision(
        allow=True,
        decision="approve_unresolved",
        reason="repair limit reached; report unresolved issues honestly",
        status=REPAIR,
        repair_attempts_used=used,
    )
