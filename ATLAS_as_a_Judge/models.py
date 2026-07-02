"""A1 data model.

Anchoring is by **unit index**, not by quoted text: the trace is pre-split into
numbered units (steps), the agent points at a unit by its integer index, and
spans are sliced deterministically in unit space. No verbatim quotes, no
locate step, no paraphrase/escaping/encoding failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Unit:
    """One pre-split, indexed piece of the trace (a step, or a line fallback)."""

    index: int
    text: str
    label: str = ""             # e.g. "context" | "step:retrieve_hop1" | "line"


@dataclass
class Onset:
    """A detected fault event, before spans are assigned. Anchored by unit."""

    unit_index: int
    codes: list[str] = field(default_factory=list)
    description: str = ""
    source: str = ""            # "forward" | "backward" | "merged"
    at_end: bool = False        # end-state fault -> snapped to the last unit


@dataclass
class FailurePoint:
    """A1 node: one fresh fault onset (a faulty unit) bound to its span.

    The span runs from this faulty unit to the next faulty unit (onset ->
    next-onset tiling, in unit space), so ``[start_unit, end_unit)`` may include
    downstream consequence/recovery units — a span is a *territory*.
    """

    index: int                  # node order
    unit_index: int             # the onset unit (anchor)
    codes: list[str]
    description: str
    start_unit: int
    end_unit: int               # exclusive
    span_text: str
    source: str = "merged"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "unit_index": self.unit_index,
            "codes": list(self.codes),
            "description": self.description,
            "units": [self.start_unit, self.end_unit],
            "source": self.source,
        }


@dataclass
class A1Result:
    """Output of A1: ordered failure-point nodes + provenance + warnings."""

    failure_points: list  # list[FailurePoint]
    n_units: int = 0
    forward: list = field(default_factory=list)    # list[Onset]
    backward: list = field(default_factory=list)   # list[Onset]
    cross: list = field(default_factory=list)      # list[Onset] (cross-examination)
    warnings: list = field(default_factory=list)   # list[str]

    def to_dict(self) -> dict:
        return {
            "failure_points": [fp.to_dict() for fp in self.failure_points],
            "n_units": self.n_units,
            "n_forward": len(self.forward),
            "n_backward": len(self.backward),
            "n_cross": len(self.cross),
            "warnings": list(self.warnings),
        }


@dataclass
class CausalEdge:
    """A directed causal edge between two A1 nodes (by node index).

    Semantics: ``cause`` -> ``effect`` holds iff cause precedes effect, cause's
    faulty content reaches effect, AND effect's fault would not have occurred
    had cause been correct (counterfactual). Data flow alone is not enough.
    """

    cause: int                  # node index
    effect: int                 # node index
    rationale: str = ""

    def to_dict(self) -> dict:
        return {"cause": self.cause, "effect": self.effect, "rationale": self.rationale}


@dataclass
class A2Result:
    """Output of A2: the causal DAG over A1's nodes + derived levels.

    ``levels`` is the longest-path layer of each node (roots = 0; a node that is
    the effect of causes at levels L sits at max(L)+1) — the local/regional
    ancestor hierarchy, computed deterministically from the edges.
    ``standalone`` lists nodes with no edges at all (self-loop / isolated).
    """

    nodes: list                 # list[FailurePoint], passed through from A1
    edges: list                 # list[CausalEdge]
    levels: dict                # node index -> int
    standalone: list            # node indices with no in/out edges
    warnings: list

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "levels": dict(self.levels),
            "standalone": list(self.standalone),
            "warnings": list(self.warnings),
        }
