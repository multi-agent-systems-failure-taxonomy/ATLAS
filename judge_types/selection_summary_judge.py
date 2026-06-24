"""Selection-Summary Judge — labeled failures -> compressed selection signal.

Not a true LLM judge — a deterministic compression of the Reflection Judge's
rich output into the buckets a search algorithm (GEPA, AdaEvolve, etc.) needs
for candidate selection:

  - root_failure_modes
  - candidate_attributable_failure_modes
  - external_or_environmental_failure_modes
  - unrecovered_failure_modes / recovered_failure_modes
  - terminal_symptom_modes / isolated_failure_modes
  - actionable_failure_modes / high_severity_failure_modes
  - outcome_linked_failure_modes
  - unmapped_failure_points / weak_taxonomy_matches  (refinement signals)

The Reflection Judge already calls this function internally; this module
exposes it as a standalone judge so callers can re-derive the summary from a
stored Reflection Judge output (or from any compatible failure_points +
relations payload) without re-running the LLM.

Underlying implementation:
    judge_types.reflection_judge.selection.derive_selection_summary
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .reflection_judge.selection import derive_selection_summary


def run(
    failure_points: Sequence[Mapping[str, Any]],
    relations: Sequence[Mapping[str, Any]] | None = None,
    *,
    weak_threshold: float = 0.5,
    strong_threshold: float = 0.7,
) -> dict:
    """Compute the compressed selection summary deterministically.

    Parameters
    ----------
    failure_points
        Per-failure-point dicts in the Reflection Judge output shape
        (must contain ``taxonomy_mappings``, ``causal_role``,
        ``recovery_status``, ``actionability``, etc.).
    relations
        Optional list of relation dicts (currently unused but reserved for
        future graph-based summaries).
    weak_threshold
        Mappings with ``mapping_confidence`` below this go into
        ``weak_taxonomy_matches``.
    strong_threshold
        Reserved for future tiering.

    Returns
    -------
    dict
        Selection-summary buckets (see module docstring).
    """
    return derive_selection_summary(
        failure_points,
        relations,
        weak_threshold=weak_threshold,
        strong_threshold=strong_threshold,
    )


__all__ = ["run"]
