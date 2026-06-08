"""Induction engine — same pipeline for seed-time and T1.

Wraps `atlas.generate_taxonomy` and adds the quality floor that gates
promotion from MAST to an induced taxonomy:

  1. Drop codes whose support is < min_support_per_code (default 2 traces).
  2. Require >= K surviving codes (default 8) across A/B/C combined.
  3. On floor failure, return None — the caller falls back to MAST and
     surfaces a "low-confidence, using MAST" message.

The strong inducer model is pinned to claude-opus-4-8 by default, INDEPENDENT
of the runtime agent's model. Solver model decides what failures appear in
traces; inducer model decides how cleanly they get categorized. See the
feedback-taxonomy-inducer-model memory in the parent project.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    from atlas import generate_taxonomy  # public atlas package
except ImportError as e:
    raise ImportError(
        "The 'atlas' package is required for induction. Install with: "
        "pip install git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
    ) from e

from claude_code_skill.accumulator import Trace

logger = logging.getLogger(__name__)

DEFAULT_INDUCER_MODEL = "claude-opus-4-8"


@dataclass
class InductionResult:
    taxonomy: Optional[dict[str, Any]]
    promoted: bool
    reason: str
    raw_taxonomy: Optional[dict[str, Any]] = None  # pre-floor, for debugging


def _trace_to_loader_dict(trace: Trace) -> dict[str, Any]:
    """Map our Trace dataclass to a dict the atlas loader can ingest.

    atlas.traces.loader.load_traces accepts a list of dicts in the
    ATLAS-unified shape — `raw_trajectory` is the trajectory field it looks
    for first."""
    return {
        "task_id": trace.task_id,
        "raw_trajectory": trace.transcript,
        "tool_calls": trace.tool_calls,
        "evidence": trace.evidence,
        "outcome": trace.outcome,
        "final_gate_status": trace.final_gate_status,
    }


def _apply_quality_floor(
    taxonomy: dict[str, Any],
    *,
    min_support_per_code: int,
    min_total_codes: int,
) -> tuple[Optional[dict[str, Any]], str]:
    """Drop singleton codes; verify >= K surviving codes."""
    if not taxonomy:
        return None, "induction returned empty taxonomy"

    annot = dict(taxonomy.get("annotation_layer", {}))
    full = dict(taxonomy.get("full_layer", {}))
    survivors_total = 0
    dropped: list[str] = []

    for axis in ("category_a", "category_b", "category_c"):
        codes = annot.get(axis, [])
        kept_codes = []
        for c in codes:
            # ATLAS reports per-code support in full_layer's matching code's
            # trace_evidence list — if absent, treat as unknown and keep.
            cid = c.get("code") or c.get("id")
            support = _support_for(cid, full.get(axis, []))
            if support >= min_support_per_code:
                kept_codes.append(c)
            else:
                dropped.append(f"{cid} (support={support})")
        annot[axis] = kept_codes
        survivors_total += len(kept_codes)

    if survivors_total < min_total_codes:
        return None, (
            f"quality floor failed: only {survivors_total} of >= {min_total_codes} "
            f"surviving codes after support>={min_support_per_code} cut "
            f"(dropped {len(dropped)}: {', '.join(dropped[:5])}{'...' if len(dropped) > 5 else ''})"
        )

    out = dict(taxonomy)
    out["annotation_layer"] = annot
    md = dict(out.get("metadata", {}))
    md["quality_floor_applied"] = {
        "min_support_per_code": min_support_per_code,
        "min_total_codes": min_total_codes,
        "dropped": dropped,
        "survivors_total": survivors_total,
    }
    out["metadata"] = md
    return out, f"promoted ({survivors_total} surviving codes)"


def _support_for(code_id: Any, full_axis_codes: list[dict[str, Any]]) -> int:
    """Count distinct traces where `code_id` fires, per the full_layer's
    `trace_evidence` list (or `support` field if pre-aggregated)."""
    if not code_id:
        return 0
    for c in full_axis_codes:
        if c.get("code") == code_id or c.get("id") == code_id:
            if "support" in c:
                try:
                    return int(c["support"])
                except (TypeError, ValueError):
                    pass
            ev = c.get("trace_evidence", [])
            return len(ev) if isinstance(ev, list) else 0
    return 0


def induce(
    traces: list[Trace],
    *,
    model: str = DEFAULT_INDUCER_MODEL,
    min_support_per_code: int = 2,
    min_total_codes: int = 8,
    max_codes: int = 30,
    output_dir: Optional[Path] = None,
) -> InductionResult:
    """One induction pass (seed-time OR T1).

    On floor failure, the result has promoted=False and taxonomy=None — the
    caller is expected to keep MAST live and surface the failure reason.
    """
    if not traces:
        return InductionResult(taxonomy=None, promoted=False,
                               reason="no traces supplied")

    payload = [_trace_to_loader_dict(t) for t in traces]
    raw = generate_taxonomy(
        traces=payload,
        output_dir=str(output_dir) if output_dir else None,
        model=model,
        max_codes=max_codes,
        save_intermediate=output_dir is not None,
        verbose=False,
    )
    floored, reason = _apply_quality_floor(
        raw,
        min_support_per_code=min_support_per_code,
        min_total_codes=min_total_codes,
    )
    if floored is None:
        logger.warning("induction floor failed: %s", reason)
        return InductionResult(
            taxonomy=None, promoted=False, reason=reason, raw_taxonomy=raw,
        )
    return InductionResult(
        taxonomy=floored, promoted=True, reason=reason, raw_taxonomy=raw,
    )


if __name__ == "__main__":
    import argparse, sys

    ap = argparse.ArgumentParser(description="Run an induction pass on a JSON trace file.")
    ap.add_argument("--traces", required=True,
                    help="Path to a JSONL/JSON file of trace dicts")
    ap.add_argument("--model", default=DEFAULT_INDUCER_MODEL)
    ap.add_argument("--min-support", type=int, default=2)
    ap.add_argument("--min-codes", type=int, default=8)
    ap.add_argument("--max-codes", type=int, default=30)
    args = ap.parse_args()

    path = Path(args.traces)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        traces_raw = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        traces_raw = json.loads(text)
    # Coerce into Trace dataclasses (only the fields we need)
    coerced = [Trace(**{**{"task_id": "?", "transcript": [], "tool_calls": [],
                            "final_gate_status": "MISSING",
                            "repair_attempts_used": 0,
                            "evidence": "",
                            "outcome": "seed"},
                          **{k: v for k, v in t.items()
                             if k in Trace.__dataclass_fields__}})
                for t in traces_raw]
    res = induce(coerced, model=args.model,
                 min_support_per_code=args.min_support,
                 min_total_codes=args.min_codes,
                 max_codes=args.max_codes)
    print(f"promoted={res.promoted}  reason={res.reason}", file=sys.stderr)
    if res.taxonomy:
        print(json.dumps(res.taxonomy, indent=2))
