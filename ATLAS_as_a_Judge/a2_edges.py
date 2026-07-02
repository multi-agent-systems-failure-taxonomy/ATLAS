"""A2 — causal edges + leveling: A1 nodes -> causal DAG.

Pipeline
--------
1. **draw edges** (LLM, one holistic call) -> candidate directed edges between
   node ids, per the counterfactual definition (an edge A->B means B's fault
   would not have occurred had A been correct — not mere data flow).
2. **validate + prune** (deterministic) -> drop unknown ids, self-edges, and
   any non-forward edge (cause must precede effect in unit order). The forward
   constraint makes the result a DAG by construction.
3. **level** (deterministic) -> longest-path layer per node (roots = 0), the
   local -> regional ancestor hierarchy.

The LLM does the semantic part (which edges exist); Python does the structural
part (acyclicity + levels).
"""

from __future__ import annotations

from typing import Optional

from .llm_agent import LLMAgent
from .models import A2Result, CausalEdge
from .splitter import split_units
from . import prompts


def _coerce_edges(payload: dict) -> list[tuple[int, int, str]]:
    items = payload.get("edges")
    if not isinstance(items, list):
        return []
    out: list[tuple[int, int, str]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            cause = int(it.get("cause"))
            effect = int(it.get("effect"))
        except (TypeError, ValueError):
            continue
        out.append((cause, effect, str(it.get("rationale", "") or "")))
    return out


def _validate_prune(raw_edges, nodes, warnings: list[str]) -> list[CausalEdge]:
    by_index = {n.index: n for n in nodes}
    kept: list[CausalEdge] = []
    seen: set[tuple[int, int]] = set()
    for cause, effect, rationale in raw_edges:
        if cause not in by_index or effect not in by_index:
            warnings.append(f"dropped edge with unknown node id: {cause}->{effect}")
            continue
        if cause == effect:
            warnings.append(f"dropped self-edge {cause}->{effect} (standalone is derived)")
            continue
        if by_index[cause].unit_index >= by_index[effect].unit_index:
            warnings.append(
                f"dropped non-forward edge {cause}->{effect} "
                f"(cause unit {by_index[cause].unit_index} >= effect unit "
                f"{by_index[effect].unit_index})"
            )
            continue
        key = (cause, effect)
        if key in seen:
            continue
        seen.add(key)
        kept.append(CausalEdge(cause=cause, effect=effect, rationale=rationale))
    return kept


def _compute_levels(nodes, edges) -> dict[int, int]:
    """Longest-path layer per node. Processing nodes in unit order is a valid
    topological order because every kept edge goes strictly forward in unit."""
    incoming: dict[int, list[int]] = {n.index: [] for n in nodes}
    for e in edges:
        if e.cause != e.effect:
            incoming[e.effect].append(e.cause)
    level: dict[int, int] = {}
    for n in sorted(nodes, key=lambda n: n.unit_index):
        causes = incoming.get(n.index, [])
        level[n.index] = 0 if not causes else 1 + max(level[c] for c in causes)
    return level


def _standalone_nodes(nodes, edges) -> list[int]:
    touched: set[int] = set()
    for e in edges:
        touched.add(e.cause)
        touched.add(e.effect)
    return [n.index for n in nodes if n.index not in touched]


def build_causal_edges(
    task: str,
    trajectory: str,
    nodes: list,
    *,
    agent: Optional[LLMAgent] = None,
) -> A2Result:
    """Run A2: draw the causal DAG over A1's ``nodes`` (a list of FailurePoint).

    ``trajectory`` is re-split into the same units A1 used, so the judge sees the
    trace content behind each node. Returns the nodes (passed through), the
    validated causal edges, the per-node levels, and standalone (isolated) nodes.
    """
    agent = agent or LLMAgent()
    warnings: list[str] = []

    if len(nodes) <= 1:
        # 0 or 1 node: no edge is possible; a lone node is standalone.
        return A2Result(
            nodes=list(nodes),
            edges=[],
            levels={n.index: 0 for n in nodes},
            standalone=[n.index for n in nodes],
            warnings=warnings,
        )

    units = split_units(trajectory)
    payload = agent.json(
        prompts.edges_prompt(task, prompts.render_units(units), prompts.render_nodes(nodes))
    )
    edges = _validate_prune(_coerce_edges(payload), nodes, warnings)
    levels = _compute_levels(nodes, edges)
    standalone = _standalone_nodes(nodes, edges)
    return A2Result(
        nodes=list(nodes),
        edges=edges,
        levels=levels,
        standalone=standalone,
        warnings=warnings,
    )


def build_graph(
    task, trajectory, taxonomy, *,
    agent: Optional[LLMAgent] = None,
    edges_agent: Optional[LLMAgent] = None,
    two_pass: bool = True,
    references: Optional[list] = None,
):
    """Convenience: run A1 then A2. Returns ``(a1_result, a2_result)``.

    ``agent`` drives both A1 and A2 unless ``edges_agent`` is given (lets A1
    detection and A2 edge-drawing use different models). ``two_pass=False``
    skips A1's backward pass to cut cost. ``references`` enables A1's
    cross-examination pass (independent solutions to the same task).
    """
    from .a1_nodes import identify_failure_points

    agent = agent or LLMAgent()
    a1 = identify_failure_points(
        task, trajectory, taxonomy,
        agent=agent, two_pass=two_pass, references=references,
    )
    a2 = build_causal_edges(task, trajectory, a1.failure_points, agent=edges_agent or agent)
    return a1, a2
