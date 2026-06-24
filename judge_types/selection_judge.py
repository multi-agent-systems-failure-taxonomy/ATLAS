"""Selection Judge — trace + taxonomy -> flat failure-mode labels.

Wraps the existing post-generation acceptance check in
``atlas_runtime.taxonomy_check``. That check is the canonical Selection Judge:
it walks a frozen batch of traces, asks the model which codes fire per trace,
and returns the active-code set + per-trace annotations.

Used for:
  - candidate selection / comparison;
  - failure-mode statistics;
  - validation-set analysis.

Output (per call):
    {
      "failure_modes": [
        {"code": "A.3", "name": "Premature termination",
         "evidence": "...", "confidence": "high", "severity": "major"},
        ...
      ],
      "none_apply": bool,
    }

This module's primary entry point ``run`` is a thin shim that converts
``taxonomy_check.check_taxonomy``'s per-batch ``annotations`` into the
Selection-Judge result shape. Callers that already use
``check_taxonomy`` directly can keep doing so.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from atlas_runtime import taxonomy_check
from atlas_runtime.program import ProgramWorkspace


def run(
    workspace: ProgramWorkspace,
    candidate: Mapping[str, Any],
    *,
    atlas_model: str,
    judge_call: Optional[Callable[[str, str], str]] = None,
) -> dict:
    """Run the Selection Judge over the workspace's pending traces.

    Parameters
    ----------
    workspace, candidate, atlas_model, judge_call
        Passed straight to ``taxonomy_check.check_taxonomy``.

    Returns
    -------
    dict with keys ``accepted`` (bool), ``active_codes`` (list[str]),
    ``annotations`` (per-trace code firings), ``snapshot_count`` (int),
    ``reason`` (str), and ``candidate`` (the support-augmented candidate).
    """
    result = taxonomy_check.check_taxonomy(
        workspace,
        dict(candidate),
        atlas_model=atlas_model,
        judge_call=judge_call,
    )
    return {
        "accepted": result.accepted,
        "active_codes": list(result.active_codes),
        "annotations": list(result.annotations),
        "snapshot_count": result.snapshot_count,
        "reason": result.reason,
        "candidate": result.candidate,
    }


__all__ = ["run"]
