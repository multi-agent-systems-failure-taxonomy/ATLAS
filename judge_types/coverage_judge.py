"""Coverage / Discovery Judge — does the taxonomy cover this failure? [PLACEHOLDER]

Asks per-trace (or per-failure-point) questions like:

  - Is this failure already covered by the current taxonomy?
  - Is it partially covered?
  - Is it not covered at all?
  - Should a new taxonomy code be proposed?
  - Is an existing code too broad or too narrow?

Drives taxonomy expansion and refinement. The Reflection Judge surfaces
``unmapped_failure_points`` and ``weak_taxonomy_matches`` in its
``selection_summary``, which approximates this signal; a dedicated Coverage
Judge is a focused, cheaper alternative when full reflection is overkill.

Status: placeholder.

Input::

    {
      "trace": "...",                # or "failure_point": {...}
      "taxonomy": [...]              # list of code dicts or prompt_block string
    }

Output::

    {
      "coverage_status": "covered" | "partially_covered" | "not_covered",
      "closest_codes": ["A.3", "B.1"],
      "missing_failure_pattern": "No fallback after external tool quota failure",
      "suggest_new_code": true
    }
"""

from __future__ import annotations

from typing import Any, Mapping


def run(payload: Mapping[str, Any]) -> dict:
    """Return coverage assessment for a trace or failure point.

    Currently raises NotImplementedError. A real implementation could share
    the mapping-stage prompts with the Reflection Judge but emit a coverage
    verdict instead of code assignments.
    """
    raise NotImplementedError(
        "CoverageJudge is a placeholder. Reflection Judge currently emits "
        "unmapped_failure_points + weak_taxonomy_matches as an approximation."
    )


__all__ = ["run"]
