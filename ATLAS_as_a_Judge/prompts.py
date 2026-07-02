"""Prompt loading + building for the three A1 passes (unit-index anchoring)."""

from __future__ import annotations

import json
from pathlib import Path
from string import Template

_ASSETS = Path(__file__).resolve().parent / "assets"


def _load(name: str) -> str:
    return (_ASSETS / name).read_text(encoding="utf-8")


_FORWARD = _load("a1_forward.md")
_BACKWARD = _load("a1_backward.md")
_MERGE = _load("a1_merge.md")
_CROSS = _load("a1_cross.md")
_EDGES = _load("a2_edges.md")
_COMPONENT_B = _load("component_b.md")

# The edge-construction guide is a doc at the package root (human-readable AND
# injected into the A2 prompt so the judge applies it).
_GUIDE = (Path(__file__).resolve().parent / "CAUSAL_HANDBOOK.md").read_text(encoding="utf-8")


def render_units(units) -> str:
    """Render the pre-split units with their index tags for the prompt."""
    return "\n\n".join(f"[UNIT {u.index}] ({u.label})\n{u.text}" for u in units)


def forward_prompt(task: str, units_block: str, taxonomy: str) -> str:
    return Template(_FORWARD).substitute(task=task, units=units_block, taxonomy=taxonomy)


def backward_prompt(task: str, units_block: str, taxonomy: str) -> str:
    return Template(_BACKWARD).substitute(task=task, units=units_block, taxonomy=taxonomy)


def cross_prompt(task: str, artifact: str, references, taxonomy: str) -> str:
    refs_block = "\n\n".join(
        f"[REFERENCE {i + 1}]\n{r}" for i, r in enumerate(references)
    )
    return Template(_CROSS).substitute(
        task=task,
        artifact=artifact,
        references=refs_block,
        n_refs=str(len(references)),
        taxonomy=taxonomy,
    )


def _render_onsets(onsets) -> str:
    return json.dumps(
        [
            {"unit_index": o.unit_index, "codes": list(o.codes), "description": o.description}
            for o in onsets
        ],
        indent=2,
        ensure_ascii=False,
    )


def merge_prompt(taxonomy: str, forward, backward, mode: str = "union") -> str:
    return Template(_MERGE).substitute(
        taxonomy=taxonomy,
        forward=_render_onsets(forward),
        backward=_render_onsets(backward),
    )


# ── A2: edges ───────────────────────────────────────────────────────────────

def render_nodes(nodes) -> str:
    """Render A1 nodes with their node id, anchor unit, codes, and description."""
    lines = []
    for n in nodes:
        codes = ",".join(n.codes)
        desc = " ".join((n.description or "").split())
        lines.append(f"[NODE {n.index}] unit={n.unit_index} codes=[{codes}] :: {desc}")
    return "\n".join(lines)


def edges_prompt(task: str, units_block: str, nodes_block: str) -> str:
    return Template(_EDGES).substitute(
        task=task, units=units_block, nodes=nodes_block, guide=_GUIDE
    )


# ── Component B: verdict ─────────────────────────────────────────────────────

def verdict_prompt(task: str, trace: str, graph_block: str) -> str:
    return Template(_COMPONENT_B).substitute(task=task, trace=trace, graph=graph_block)
