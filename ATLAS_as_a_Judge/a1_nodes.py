"""A1 — node creation: trace -> failure-point nodes (unit-index anchoring).

Pipeline
--------
0. **pre-split** (deterministic) -> numbered units (steps).
1. **forward pass**  (LLM) -> faulty unit indices, read unit 0 -> last.
2. **backward pass** (LLM) -> faulty unit indices, read last -> unit 0 (hindsight).
3. **merge**         (LLM) -> deduplicated union of unit indices (same unit ->
   one node, union codes). Deterministic union fallback if the call fails.
4. **tile**          (deterministic) -> validate indices, dedup, sort, and tile
   spans onset-unit -> next-onset-unit.

The agent only ever emits integer unit indices + codes — never quoted text — so
there is no locate/quote/encoding failure mode.
"""

from __future__ import annotations

from typing import Optional

from .llm_agent import LLMAgent
from .models import A1Result, FailurePoint, Onset
from .splitter import split_units
from . import prompts


# ── taxonomy rendering ──────────────────────────────────────────────────────

def _taxonomy_block(taxonomy) -> str:
    if hasattr(taxonomy, "prompt_block"):
        return taxonomy.prompt_block()
    if isinstance(taxonomy, dict) and isinstance(taxonomy.get("codes"), list):
        lines = []
        for c in taxonomy["codes"]:
            cid = c.get("id") or c.get("code") or "?"
            name = c.get("name", "")
            desc = c.get("description") or c.get("definition") or ""
            lines.append(f"  {cid}: {name}\n      {desc}")
        return "\n".join(lines)
    return str(taxonomy)


# ── LLM output -> onsets ────────────────────────────────────────────────────

def _coerce_onsets(payload: dict, source: str) -> list[Onset]:
    items = payload.get("failure_points")
    if not isinstance(items, list):
        return []
    out: list[Onset] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        at_end = bool(it.get("at_end", False))
        ui = it.get("unit_index")
        if not isinstance(ui, int):
            try:
                ui = int(str(ui).strip())
            except (TypeError, ValueError):
                if not at_end:
                    continue
                ui = -1  # end-anchored: index is ignored and snapped later
        codes = it.get("codes") or []
        if isinstance(codes, str):
            codes = [codes]
        codes = [str(c).strip() for c in codes if str(c).strip()]
        out.append(
            Onset(
                unit_index=ui,
                codes=codes,
                description=str(it.get("description", "") or ""),
                source=source,
                at_end=at_end,
            )
        )
    return out


# ── passes ──────────────────────────────────────────────────────────────────

def _detect(agent, task, units_block, taxonomy_block, direction: str) -> list[Onset]:
    builder = prompts.forward_prompt if direction == "forward" else prompts.backward_prompt
    payload = agent.json(builder(task, units_block, taxonomy_block))
    return _coerce_onsets(payload, direction)


def _detect_cross(agent, task, units, taxonomy_block, references) -> list[Onset]:
    """Cross-examination pass: compare the final artifact against independent
    reference solutions to the same task. Fires taxonomy codes only where the
    references AGREE on behavior the artifact lacks. Onsets are end-anchored
    (properties of the final artifact, not of a trace step)."""
    artifact = units[-1].text if units else ""
    payload = agent.json(
        prompts.cross_prompt(task, artifact, list(references), taxonomy_block)
    )
    onsets = _coerce_onsets(payload, "cross")
    for o in onsets:
        o.at_end = True  # cross findings are artifact properties by definition
    return onsets


def _merge(agent, taxonomy_block, forward, backward) -> list[Onset]:
    if not forward and not backward:
        return []
    if not forward:
        return [Onset(o.unit_index, list(o.codes), o.description, "merged") for o in backward]
    if not backward:
        return [Onset(o.unit_index, list(o.codes), o.description, "merged") for o in forward]
    payload = agent.json(prompts.merge_prompt(taxonomy_block, forward, backward))
    merged = _coerce_onsets(payload, "merged")
    return merged if merged else _fallback_union(forward, backward)


def _fallback_union(forward, backward) -> list[Onset]:
    """Deterministic union by unit_index, used only if the merge call yields nothing."""
    seen: dict[int, Onset] = {}
    for o in list(forward) + list(backward):
        if o.unit_index in seen:
            for c in o.codes:
                if c not in seen[o.unit_index].codes:
                    seen[o.unit_index].codes.append(c)
        else:
            seen[o.unit_index] = Onset(o.unit_index, list(o.codes), o.description, "merged")
    return list(seen.values())


# ── tile ────────────────────────────────────────────────────────────────────

def _tile(onsets: list[Onset], units, warnings: list[str]) -> list[FailurePoint]:
    n = len(units)

    # validate range, dedup by unit_index (union codes)
    by_idx: dict[int, Onset] = {}
    for o in onsets:
        if not (0 <= o.unit_index < n):
            warnings.append(f"dropped out-of-range unit_index {o.unit_index} (n_units={n})")
            continue
        if o.unit_index in by_idx:
            for c in o.codes:
                if c not in by_idx[o.unit_index].codes:
                    by_idx[o.unit_index].codes.append(c)
        else:
            by_idx[o.unit_index] = Onset(o.unit_index, list(o.codes), o.description, o.source)

    faulty = sorted(by_idx)
    points: list[FailurePoint] = []
    for k, ui in enumerate(faulty):
        start_unit = ui
        end_unit = faulty[k + 1] if k + 1 < len(faulty) else n  # exclusive
        span_text = "\n\n".join(units[j].text for j in range(start_unit, end_unit))
        o = by_idx[ui]
        points.append(
            FailurePoint(
                index=k,
                unit_index=ui,
                codes=list(o.codes),
                description=o.description,
                start_unit=start_unit,
                end_unit=end_unit,
                span_text=span_text,
                source=o.source,
            )
        )
    return points


# ── public API ──────────────────────────────────────────────────────────────

def identify_failure_points(
    task: str,
    trajectory: str,
    taxonomy,
    *,
    agent: Optional[LLMAgent] = None,
    mode: str = "union",
    two_pass: bool = True,
    references: Optional[list] = None,
    cross_agent: Optional[LLMAgent] = None,
) -> A1Result:
    """Run A1: turn one trace into failure-point nodes, anchored by unit index.

    The trajectory is pre-split into numbered units; the LLM points at faulty
    units by integer index (never by quoted text). ``taxonomy`` may be a
    ``Taxonomy`` object, a flat ``{codes: [...]}`` dict (incl. MAST), or a
    pre-rendered string, and is the sole definition of "failure".

    ``references`` (optional) enables the CROSS-EXAMINATION pass: independent
    solutions/hypotheses for the same task (e.g. other agents' final patches —
    content only, never outcome labels). The cross pass fires taxonomy codes
    only where the references agree on behavior the final artifact lacks; its
    onsets are end-anchored and merge into the same node set. ``cross_agent``
    optionally runs the cross pass on a different (stronger) model than the
    trace passes — regime-adaptive cost control.
    """
    agent = agent or LLMAgent()
    units = split_units(trajectory)
    taxonomy_block = _taxonomy_block(taxonomy)
    units_block = prompts.render_units(units)
    warnings: list[str] = []

    forward = _detect(agent, task, units_block, taxonomy_block, "forward")
    # two_pass=False skips the backward pass (and its merge) — a ~1/3 cost cut
    # per A1 at some recall; backward left empty makes _merge degenerate to forward.
    backward = (
        _detect(agent, task, units_block, taxonomy_block, "backward")
        if two_pass
        else []
    )

    # End-state faults (no final verdict, missing overall verification,
    # premature termination) are about the trace *ending* without something —
    # anchor them to the last unit deterministically, regardless of the index
    # the model guessed. Done before merge so the correct unit flows through.
    last = len(units) - 1
    if last >= 0:
        for o in (*forward, *backward):
            if o.at_end:
                o.unit_index = last

    merged = _merge(agent, taxonomy_block, forward, backward)

    # Cross-examination pass: appended after the trace-pass merge; _tile dedups
    # by unit index (union codes), so a cross onset landing on the same last
    # unit as a trace onset folds in naturally.
    cross: list[Onset] = []
    if references:
        cross = _detect_cross(
            cross_agent or agent, task, units, taxonomy_block, references
        )
        last = len(units) - 1
        for o in cross:
            o.unit_index = last
        merged = merged + cross

    points = _tile(merged, units, warnings)

    return A1Result(
        failure_points=points,
        n_units=len(units),
        forward=forward,
        backward=backward,
        cross=cross,
        warnings=warnings,
    )
