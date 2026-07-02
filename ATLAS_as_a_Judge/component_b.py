"""Component B — read the failure graph (+ trace) and decide task correct/incorrect.

The graph is neutral evidence, not a verdict: a failure graph does NOT
automatically mean the task failed (failures can be recovered from / be
non-terminal). B weighs the graph against the agent's final result and returns
a binary verdict with a confidence and the codes most responsible.

Output matches the `binary_judge_eval` JudgeOutput contract:
``{verdict, confidence, failure_codes, evidence, raw_response}``.
"""

from __future__ import annotations

import json
from typing import Optional

from .llm_agent import LLMAgent
from . import prompts


def _render_graph(a2) -> str:
    if not a2.nodes:
        return "(no failure points detected in the trace)"
    has_out = {e.cause for e in a2.edges}
    lines = ["Failure points (node id, level, codes):"]
    for n in a2.nodes:
        tag = " [terminal — no downstream effect]" if n.index not in has_out else ""
        if getattr(n, "source", "") == "cross":
            tag = (
                " [CROSS-EXAMINATION: independent reference solutions to this"
                " task converge on behavior this solution lacks]"
            )
        desc = " ".join((n.description or "").split())
        lines.append(f"  N{n.index} L{a2.levels.get(n.index, 0)} {n.codes}{tag}: {desc[:170]}")
    if a2.edges:
        lines.append("Causal edges (cause -> effect):")
        for e in a2.edges:
            lines.append(f"  N{e.cause} -> N{e.effect}: {' '.join((e.rationale or '').split())[:120]}")
    else:
        lines.append("Causal edges: (none)")
    if a2.standalone:
        lines.append(f"Standalone (isolated) failure points: {a2.standalone}")
    return "\n".join(lines)


def _as_str_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    return [str(v) for v in value if str(v).strip()]


def judge_correctness(task: str, trace: str, a2, *, agent: Optional[LLMAgent] = None) -> dict:
    """Decide whether the agent solved the task, using the failure graph as evidence."""
    agent = agent or LLMAgent()
    payload = agent.json(prompts.verdict_prompt(task, trace, _render_graph(a2)))

    verdict = payload.get("verdict")
    verdict = verdict if verdict in ("correct", "incorrect") else "incorrect"
    try:
        conf = float(payload.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.5
    conf = min(1.0, max(0.0, conf))

    return {
        "verdict": verdict,
        "confidence": conf,
        "failure_codes": _as_str_list(payload.get("failure_codes")),
        "evidence": _as_str_list(payload.get("evidence"))[:6],
        "raw_response": json.dumps(payload, ensure_ascii=False)[:2000],
    }
