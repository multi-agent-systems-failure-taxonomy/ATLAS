"""ATLAS-as-a-Judge.

Turns an agent execution trace into a causal graph of failure points, kept
strictly separate from any success/fail verdict. Component B (graph -> outcome)
is a different thing and lives elsewhere.

Component A (graph builder) has two sub-components:

- **A1 — node creation** (this module's :func:`identify_failure_points`):
  identify failure points (nodes) and their spans. The trace is pre-split into
  numbered units (steps); the LLM anchors each failure point by integer
  **unit index** (never by quoted text). Detection is a forward pass + a
  backward pass, merged at the unit level (default union), then spans are tiled
  onset-unit -> next-onset-unit. All three passes use an LLM agent (default
  Sonnet 4.5).

- **A2 — edges + leveling**: not built yet.
"""

from __future__ import annotations

from .llm_agent import DEFAULT_MODEL, LLMAgent
from .models import A1Result, A2Result, CausalEdge, FailurePoint, Onset, Unit
from .splitter import split_units
from .a1_nodes import identify_failure_points
from .a2_edges import build_causal_edges, build_graph
from .component_b import judge_correctness

__all__ = [
    "DEFAULT_MODEL",
    "LLMAgent",
    "Unit",
    "Onset",
    "FailurePoint",
    "A1Result",
    "CausalEdge",
    "A2Result",
    "split_units",
    "identify_failure_points",
    "build_causal_edges",
    "build_graph",
    "judge_correctness",
]
