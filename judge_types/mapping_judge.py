"""Mapping Judge — failure_point + taxonomy -> best code(s). [PLACEHOLDER]

Modular sub-judge used when the failure-point detector and the code-assignment
step are split into separate passes. The Reflection Judge's two-call mode
performs this internally (see ``reflection_judge.judge``); this module exists
so that callers can run the mapping step in isolation against
already-identified failure points.

Status: placeholder. The contract below is what a real implementation must
honor.

Input::

    {
      "failure_point": "Agent stopped after API error without fallback.",
      "evidence": "...",
      "taxonomy": [...],   # list of {code, name, definition, ...} (or a
                           # Taxonomy.prompt_block() string)
    }

Output::

    {
      "primary_code": "A.4",
      "secondary_codes": ["B.2"],
      "mapping_confidence": 0.88,   # 0.0-1.0
      "unmapped": false,
      "proposed_failure_mode": null # only when unmapped=true
    }
"""

from __future__ import annotations

from typing import Any, Mapping


def run(failure_point: Mapping[str, Any]) -> dict:
    """Assign taxonomy code(s) to one already-identified failure point.

    Currently raises NotImplementedError. A real implementation should reuse
    the prompts under ``reflection_judge.prompts.MAPPING_SYSTEM`` and call
    the configured LLM transport (see ``reflection_judge._llm``).
    """
    raise NotImplementedError(
        "MappingJudge is a placeholder. The Reflection Judge currently "
        "performs mapping internally in its two_call mode; a standalone "
        "implementation will reuse reflection_judge.prompts.MAPPING_SYSTEM."
    )


__all__ = ["run"]
