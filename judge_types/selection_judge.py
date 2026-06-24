"""Selection Judge — trace + taxonomy -> flat failure-mode labels. [PLACEHOLDER]

Shallow, batchable, scalable judge meant for downstream selection /
comparison / statistics — distinct from the Reflection Judge, which builds
a deep causal graph. The Selection Judge identifies which taxonomy codes
appear in a trace and returns a flat list of labels with evidence.

Status: placeholder. atlas_skill previously had a single implementation
(``atlas_runtime/taxonomy_check.py``) that doubled as the post-generation
acceptance gate. That gate has been removed in favor of the Reflection
Judge + refiner (see ``atlas_runtime/reflection_refinement.py``); the
shallow per-trace classification primitive itself was not preserved.

A future implementation should be a standalone, workspace-agnostic
function: ``(trace_text, taxonomy_catalog, model) -> SelectionResult``.
GEPA's ``ATLAS_Taxonomy/judge.py::TaxonomyJudge.classify_trace`` is the
closest reference port-target.

Input::

    {
      "trace": "...",
      "taxonomy": [...]            # list of code dicts or prompt_block string
    }

Output::

    {
      "failure_modes": [
        {"code": "A.3", "name": "Premature termination",
         "evidence": "...", "confidence": "high", "severity": "major"}
      ],
      "none_apply": false
    }
"""

from __future__ import annotations

from typing import Any, Mapping


def run(payload: Mapping[str, Any]) -> dict:
    """Classify which taxonomy codes fire in a single trace.

    Currently raises NotImplementedError. The legacy implementation was tied
    to a workspace + frozen-snapshot acceptance gate; a standalone Selection
    Judge needs its own thin entry point (see module docstring).
    """
    raise NotImplementedError(
        "SelectionJudge is a placeholder. The legacy taxonomy_check that "
        "doubled as the generation gate has been removed; a standalone "
        "shallow classifier has not yet been ported. See "
        "GEPA/ATLAS_Taxonomy/judge.py::TaxonomyJudge.classify_trace for the "
        "closest reference target."
    )


__all__ = ["run"]
