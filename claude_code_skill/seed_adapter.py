"""Seed adapter — read user-provided traces at conversation start.

Invoked as a SETUP/startup action (--seed-traces <path>), NOT mid-task by the
agent. The simple-scenario boundary: seeds are READ ONCE; they are not the
start of a persistent store.

Heavy lifting (multi-format detection) is delegated to the public atlas
package — it already handles ATLAS-unified, tau-bench, Codex CLI session,
event log, conversation/Forgecode, KIRA, and plain text. We just convert
the loader's output into the canonical Trace objects the accumulator wants.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

try:
    from atlas.traces.loader import load_traces  # public atlas package
except ImportError as e:
    raise ImportError(
        "The 'atlas' package is required for seed loading. Install with: "
        "pip install git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
    ) from e

from claude_code_skill.accumulator import Trace, TraceAccumulator, get_accumulator


def _coerce_to_trace(record: dict | object, *, fallback_id: str) -> Trace:
    """Map a load_traces() record onto our canonical Trace shape.

    The loader output's shape varies by detected format; we read defensively.
    Final-gate fields default to MISSING for seeds — they came from outside
    our hooks and the agent never produced our gate block.
    """
    if hasattr(record, "to_dict"):
        record = record.to_dict()
    if not isinstance(record, dict):
        record = {"raw": str(record)}

    task_id = (
        record.get("task_id")
        or record.get("instance_id")
        or record.get("id")
        or fallback_id
    )
    transcript = record.get("raw_trajectory") or record.get("messages") or record.get("trajectory") or []
    tool_calls = record.get("tool_calls", [])
    if not tool_calls and isinstance(transcript, list):
        tool_calls = [t for t in transcript if isinstance(t, dict) and t.get("tool_calls")]

    return Trace(
        task_id=str(task_id),
        transcript=list(transcript) if isinstance(transcript, list) else [],
        tool_calls=list(tool_calls) if isinstance(tool_calls, list) else [],
        final_gate_status="MISSING",
        repair_attempts_used=0,
        evidence=record.get("evidence", ""),
        outcome=record.get("outcome", "seed"),
        metadata={"source": "seed", "format": record.get("format", "unknown")},
    )


def load_seed_into(
    path: Path,
    accumulator: TraceAccumulator | None = None,
) -> int:
    """Read seed traces from path (file or directory) and append to the accumulator.

    Returns the number of traces loaded.
    """
    acc = accumulator or get_accumulator()
    loaded = load_traces(str(path), verbose=False)
    count = 0
    for i, rec in enumerate(loaded):
        trace = _coerce_to_trace(rec, fallback_id=f"seed-{i:04d}")
        acc.add_trace(trace)
        count += 1
    return count


def load_seeds(paths: Iterable[Path]) -> int:
    acc = get_accumulator()
    total = 0
    for p in paths:
        total += load_seed_into(p, accumulator=acc)
    return total


if __name__ == "__main__":
    import argparse, sys

    ap = argparse.ArgumentParser(description="Load user seed traces into the accumulator.")
    ap.add_argument("--seed-traces", required=True,
                    help="Path to a seed file or directory (any atlas-supported format)")
    args = ap.parse_args()

    n = load_seed_into(Path(args.seed_traces))
    print(f"loaded {n} seed traces from {args.seed_traces}", file=sys.stderr)
