"""Taxonomy Quality Judge — evaluate the taxonomy itself. [PLACEHOLDER]

This judge does NOT score traces. It scores the taxonomy:

  - Are codes observable?
  - Are codes distinct? Redundant pairs?
  - Are some too broad? Too rare?
  - Are important patterns missing (by inspection, not via traces)?
  - Are code definitions clear enough for reliable annotation?

Used by taxonomy generation validation and refinement (pruning / merging /
splitting). atlas_runtime/refinement.py already has a narrow precursor
(``_model_refinement_judge``) that runs against refinement candidates; a real
Quality Judge would generalize that to evaluate any taxonomy on demand.

Status: placeholder.

Input::

    {
      "taxonomy": [...],            # list of code dicts or prompt_block string
      "support_traces": [...]       # optional supporting evidence
    }

Output::

    {
      "code_quality": [
        {"code": "A.3",
         "issue": "overlaps with A.5",
         "recommendation": "split premature termination from invalid finalization"}
      ],
      "overall_quality": "good" | "needs_refinement" | "poor"
    }
"""

from __future__ import annotations

from typing import Any, Mapping


def run(payload: Mapping[str, Any]) -> dict:
    """Score a taxonomy's own code-set quality.

    Currently raises NotImplementedError. The narrow precursor in
    atlas_runtime/refinement.py::_model_refinement_judge can serve as a
    starting point.
    """
    raise NotImplementedError(
        "QualityJudge is a placeholder. See "
        "atlas_runtime/refinement.py::_model_refinement_judge for a narrow "
        "precursor scoped to refinement candidates."
    )


__all__ = ["run"]
