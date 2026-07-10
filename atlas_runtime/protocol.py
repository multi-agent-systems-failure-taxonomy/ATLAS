"""The minimal pre-submission ATLAS protocol.

This is deliberately narrower than the earlier ATLAS protocol: there are no
mid-task checkpoints, reflection workflow, task routing fields, or maturity
rules. The active taxonomy is consulted only at the pre-submission gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.resources import files
from string import Template

READY = "READY_TO_SUBMIT"
REPAIR = "REPAIR_REQUIRED"

_LINE_PREFIX = r"^[ \t]*(?:[-*]\s*)?(?:[#>]+\s*)?(?:\*\*)?[ \t]*"
_STATUS_RE = re.compile(
    rf"(?im){_LINE_PREFIX}Final\s+ATLAS\s+status"
    r"\s*(?:\*\*)?\s*[:\-]\s*(?:\*\*)?\s*([^\r\n]+)",
    re.IGNORECASE,
)
_STATUS_FIELD_RE = re.compile(
    rf"(?im){_LINE_PREFIX}Status\s*(?:\*\*)?\s*[:\-]\s*(?:\*\*)?\s*([^\r\n]+)",
    re.IGNORECASE,
)
_FINAL_DECISION_RE = re.compile(
    rf"(?im){_LINE_PREFIX}Final\s+decision"
    r"\s*(?:\*\*)?\s*[:\-]\s*(?:\*\*)?\s*([^\r\n]+)",
    re.IGNORECASE,
)
_GATE_OUTCOME_RE = re.compile(
    rf"(?im){_LINE_PREFIX}Gate\s+outcome"
    r"\s*(?:\*\*)?\s*[:\-]\s*(?:\*\*)?\s*([^\r\n]+)",
    re.IGNORECASE,
)
_FINAL_STATUS_HEADING_RE = re.compile(
    rf"(?im){_LINE_PREFIX}Final\s+ATLAS\s+status\s*(?:\*\*)?\s*:?\s*$",
    re.IGNORECASE,
)
_DECIDE_RE = re.compile(
    rf"(?im){_LINE_PREFIX}Decide\s*(?:\*\*)?\s*[:\-]\s*(?:\*\*)?\s*"
    r"((?:no\s+change\s+needed)|(?:change\s*:))",
    re.IGNORECASE,
)
_ATTEMPTS_RE = re.compile(
    r"Repair\s+attempts\s+used\s*(?:\*\*)?\s*[:\-]\s*(?:\*\*)?\s*(\d+)",
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
    template = (
        files("atlas_runtime")
        .joinpath("assets", "pre_submission_protocol.md")
        .read_text(encoding="utf-8")
    )
    return Template(template).substitute(max_retries=max_retries)


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

    statuses = extract_statuses(gate_text or "")
    attempts = _ATTEMPTS_RE.findall(gate_text or "")
    if not statuses:
        return GateDecision(
            allow=False,
            decision="block",
            reason="missing `Final ATLAS status:` block",
            status=None,
            repair_attempts_used=0,
        )

    used = int(attempts[-1]) if attempts else 0
    return _decision_for_status(
        statuses[-1], used=used, max_retries=max_retries
    )


def _decision_for_status(
    status: str, *, used: int, max_retries: int
) -> GateDecision:
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


def pin_gate_decision(
    decision: GateDecision,
    pinned_status: str | None,
    *,
    max_retries: int,
) -> tuple[GateDecision, bool]:
    """Make a status recovered before a format re-prompt authoritative.

    A re-emission that flips its verdict under re-prompt pressure is sampling
    noise, not new information; the pre-re-prompt status wins. Returns the
    effective decision and whether a flip was suppressed.
    """
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    if (
        pinned_status not in (READY, REPAIR)
        or decision.status is None
        or decision.status == pinned_status
    ):
        return decision, False
    pinned = _decision_for_status(
        pinned_status,
        used=decision.repair_attempts_used,
        max_retries=max_retries,
    )
    return (
        GateDecision(
            allow=pinned.allow,
            decision=pinned.decision,
            reason=(
                f"{pinned.reason} (verdict pinned to the pre-re-prompt "
                f"reflection; the re-emission flipped to {decision.status})"
            ),
            status=pinned.status,
            repair_attempts_used=pinned.repair_attempts_used,
        ),
        True,
    )


def extract_statuses(text: str) -> list[str]:
    """Return normalized final-gate statuses in document order.

    Agents often render the final report as Markdown headings or a small status
    table rather than the exact canonical line. Keep the accepted vocabulary
    narrow, but tolerate harmless formatting variants.
    """
    candidates: list[tuple[int, str]] = []
    for pattern in (
        _STATUS_RE,
        _STATUS_FIELD_RE,
        _FINAL_DECISION_RE,
        _GATE_OUTCOME_RE,
    ):
        for match in pattern.finditer(text):
            normalized = _normalize_status(match.group(1))
            if normalized:
                candidates.append((match.start(), normalized))
    for match in _DECIDE_RE.finditer(text):
        value = "ready" if "no change needed" in match.group(1).lower() else "repair"
        candidates.append((match.start(), _normalize_status(value) or REPAIR))
    for match in _FINAL_STATUS_HEADING_RE.finditer(text):
        for value in _status_lines_after_heading(text, match.end()):
            normalized = _normalize_status(value)
            if normalized:
                candidates.append((match.start(), normalized))
                break
    return [status for _, status in sorted(candidates)]


def _status_lines_after_heading(text: str, start: int) -> list[str]:
    lines: list[str] = []
    for raw_line in text[start:].splitlines()[:8]:
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^[#>]+|\w.+:\s*$", line):
            break
        lines.append(line)
        if len(lines) >= 4:
            break
    return lines


def _normalize_status(value: str) -> str | None:
    normalized = " ".join(
        str(value)
        .strip()
        .lower()
        .replace("_", " ")
        .replace("*", " ")
        .replace("`", " ")
        .split()
    )
    normalized = normalized.strip(" .:;,-")
    if any(
        phrase in normalized
        for phrase in (
            "repair required",
            "requires repair",
            "needs repair",
            "need repair",
            "report unresolved",
            "unresolved",
            "not ready",
            "not complete",
            "incomplete",
            "unsuccessful",
            "not successful",
            "not passed",
            "not pass",
            "did not pass",
            "unverified",
            "not verified",
            "verification failed",
            "failed verification",
        )
    ):
        return REPAIR
    if normalized in {"repair", "fail", "failed", "failure"}:
        return REPAIR
    if normalized in {
        "ready to submit",
        "ready for release",
        "ready for submission",
        "ready for final answer",
        "ready",
        "task complete",
        "computation verified",
        "complete",
        "verified",
        "pass",
        "success",
        "successful",
        "approve",
        "approved",
        "accept",
        "accepted",
        "submit",
    }:
        return READY
    if any(
        phrase in normalized
        for phrase in (
            "ready",
            "task complete",
            "complete",
            "verified",
            "pass",
            "success",
            "approved",
            "accepted",
            "submit",
            "submission",
            "compliant",
            "clearance",
            "satisfied",
            "no change needed",
        )
    ):
        return READY
    return None
