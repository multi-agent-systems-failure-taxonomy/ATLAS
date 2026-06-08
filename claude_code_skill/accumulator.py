"""In-memory trace accumulator.

Holds one running pile of completed task-attempts for the current conversation.
The Stop hook emits a Trace object on every clean completion; the accumulator
appends it. Once `count() >= T1` the induction engine fires; once
`count() - last_refined_at >= delta_n` the refinement engine fires.

There is ONE pile and ONE schema. The seed adapter normalizes user-supplied
seed traces into the same Trace dataclass, then calls add_trace() — the
downstream induction code does not distinguish between seed and in-conversation
sources.

No durable writes. The accumulator lives for the lifetime of the conversation
and disappears with the process. Persistence across conversations is OUT OF
SCOPE for the simple scenario.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class Trace:
    """Canonical trace shape — emitted by Stop hook, accepted by induction/refinement.

    One trace == one completed task-attempt. A failed-then-repaired-then-verified
    cycle is ONE trace, not three. The outcome field captures how it ended.
    """
    task_id: str
    transcript: list[dict[str, Any]]      # turn-by-turn assistant/user/tool entries
    tool_calls: list[dict[str, Any]]      # name + args + result per call
    final_gate_status: str                # "READY_TO_SUBMIT" | "REPAIR_REQUIRED" | "MISSING"
    repair_attempts_used: int             # 0..max_retries
    evidence: str                         # the Evidence field from the final-gate block
    outcome: str                          # "submitted" | "unresolved_reported"
    started_at: float = 0.0
    ended_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TraceAccumulator:
    """In-memory pile of traces for one conversation."""

    def __init__(self) -> None:
        self._traces: list[Trace] = []
        self._last_refined_at: int = 0

    def add_trace(self, trace: Trace) -> int:
        """Append a trace; return the new total count."""
        self._traces.append(trace)
        return len(self._traces)

    def count(self) -> int:
        return len(self._traces)

    def all_traces(self) -> list[Trace]:
        return list(self._traces)

    def recent(self, k: int) -> list[Trace]:
        return self._traces[-k:] if k > 0 else []

    def mark_refined(self) -> None:
        """Record that a refinement just consumed everything up to `count()`."""
        self._last_refined_at = len(self._traces)

    def since_last_refinement(self) -> int:
        return len(self._traces) - self._last_refined_at

    def reset(self) -> None:
        self._traces.clear()
        self._last_refined_at = 0


# A module-level singleton is the cheapest way to share state between the
# Stop hook (writer) and the induction/refinement runners (readers) within one
# conversation. They live in the same Python process inside Claude Code's
# hook subprocess invocations? — no: each hook fires in a fresh subprocess.
# So the singleton WORKS only inside the runners spawned by the host process.
# Hooks must reach the accumulator via the trace-store-on-disk mechanism in
# `hooks/store.py` if this simple-scenario assumption breaks. For the simple
# scenario this module-level singleton is sufficient because induction +
# refinement are invoked from the same long-lived host script that also reads
# hook output via stdout/stderr capture.
_ACC: Optional[TraceAccumulator] = None


def get_accumulator() -> TraceAccumulator:
    global _ACC
    if _ACC is None:
        _ACC = TraceAccumulator()
    return _ACC
