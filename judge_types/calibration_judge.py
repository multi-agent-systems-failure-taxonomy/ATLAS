"""Calibration / Agreement Judge — is this code assignment reliable? [PLACEHOLDER]

Audits the Selection Judge's output. Per annotation, asks:

  - Does the evidence actually support the assigned code?
  - Are judges over-triggering this code (false-positive pattern)?
  - Are two annotations of the same trace inconsistent?
  - Is the assigned confidence calibrated against the evidence?
  - Do similar traces receive similar labels?

Used for debugging taxonomy application and improving judge reliability.
Especially useful as a periodic cross-check when running the Selection Judge
in batch.

Status: placeholder.

Input::

    {
      "annotation": {"code": "A.3", "confidence": "high", ...},
      "evidence": "...",
      "taxonomy": [...]
    }

Output::

    {
      "annotation_valid": true,
      "evidence_support": "high" | "medium" | "low" | "none",
      "possible_overtrigger": false,
      "conflicting_codes": []   # codes that would also have fit
    }
"""

from __future__ import annotations

from typing import Any, Mapping


def run(payload: Mapping[str, Any]) -> dict:
    """Audit a Selection Judge annotation against its evidence + taxonomy.

    Currently raises NotImplementedError. No precursor in atlas_skill today —
    this is a new judge whose prompt and policy still need design work.
    """
    raise NotImplementedError(
        "CalibrationJudge is a placeholder. No precursor exists in atlas_skill; "
        "design work pending."
    )


__all__ = ["run"]
