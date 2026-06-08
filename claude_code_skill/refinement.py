"""Refinement engine — refine, don't regenerate.

Ported and simplified from evo-taxonomy-pipeline manager.py
(`_refine_with_feedback` / `_gather_refinement_context`). Adapted for the
simple-scenario:

  - No judge-feedback dependency: refinement evidence comes from the trace
    accumulator's recent trace excerpts and final-gate fields directly.
  - No disk-based stagnation / score-history triggers: triggered by the
    caller every ΔN traces past the previous refinement.
  - No iteration-log scanning: reads from the in-memory TraceAccumulator.
  - Stable code IDs: codes that survive a refinement keep their ID; the
    structured diff (added/promoted/demoted/merged/split/retired) is
    computed post-hoc by ID comparison.

LLM call uses the strong inducer model (claude-opus-4-8 by default) — same
model as induction, independent of the runtime agent.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from claude_code_skill.accumulator import Trace

logger = logging.getLogger(__name__)

DEFAULT_REFINER_MODEL = "claude-opus-4-8"


REFINEMENT_PROMPT = """\
You are refining an existing failure-mode taxonomy for an agent system based
on new trace evidence. The taxonomy has been live for {iterations} task
attempts since the last update. Goal: SHARPEN the taxonomy so it gives the
agent clearer signal — NOT to throw codes away.

## EXISTING TAXONOMY ({n_codes} codes)
{existing_codes}

## TRACE EVIDENCE (last {n_traces} attempts)
{trace_excerpts}

## REFINEMENT INSTRUCTIONS

Produce a cleaner taxonomy by performing exactly these operations:

1. **MERGE / DROP redundant codes.** If two codes describe the same underlying
   failure (e.g. two B-codes both flagging "solver gave a single-strategy
   answer with no derivation"), keep ONE with the clearer definition and
   remove the duplicate. Also drop codes too-fine-grained to be a single
   broader pattern.

2. **SHARPEN vague codes.** For any code whose definition is generic ("output
   has issues", "reasoning is unclear"), rewrite the definition so it names
   a concrete observable: what would have to appear in a trace for this code
   to fire, and what would NOT count.

3. **ADD codes only from concrete evidence.** Look at the trace excerpts. If
   you can point to a specific repeated pattern not cleanly captured by any
   existing code, add one. Do NOT invent codes from imagination.

   - A codes: system / infrastructure failures (handoff loss, garbled output,
     context overflow, instruction non-compliance, truncation).
   - B codes: per-role quality failures (solver / checker / refiner /
     coordinator) — every B code MUST include `applies_to_role`.
   - C codes: domain reasoning errors (wrong formula, off-by-one, missed edge
     case, unverified invariant).

4. **DO NOT cull codes just because they haven't fired yet.** Absence of
   evidence is not evidence of absence — keep them unless rule 1 or 2 forces
   removal.

5. **PRESERVE code IDs you keep.** Keep `A.3` as `A.3` if its meaning is
   essentially unchanged; don't renumber.

6. Aim for 15–30 total codes. Quality over quantity.

Return ONLY valid JSON with this exact structure (no markdown fences):

{{
  "category_a": [
    {{"code": "A.1", "name": "...", "definition": "...", "severity": "major"}}
  ],
  "category_b": [
    {{"code": "B.1", "name": "...", "definition": "...", "severity": "major", "applies_to_role": "solver"}}
  ],
  "category_c": [
    {{"code": "C.1", "name": "...", "definition": "...", "severity": "major"}}
  ],
  "refinement_notes": "1-3 sentences summarizing what you merged, sharpened, and added (and why)."
}}
"""


@dataclass
class RefinementDiff:
    added: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    sharpened: list[str] = field(default_factory=list)   # ID survived, definition changed
    severity_changed: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class RefinementResult:
    taxonomy: Optional[dict[str, Any]]    # None on failure -> caller keeps current
    diff: Optional[RefinementDiff]
    reason: str


def _format_existing_codes(taxonomy: dict[str, Any]) -> tuple[str, int]:
    lines: list[str] = []
    n = 0
    annot = taxonomy.get("annotation_layer", taxonomy)
    for cat_key, cat_label in [
        ("category_a", "A (system/infrastructure)"),
        ("category_b", "B (role-specific quality)"),
        ("category_c", "C (domain reasoning)"),
    ]:
        codes = annot.get(cat_key, [])
        for c in codes:
            cid = c.get("code") or c.get("id") or "?"
            name = c.get("name", "?")
            defn = (c.get("definition") or c.get("description") or "")[:200]
            role = c.get("applies_to_role") or c.get("role") or ""
            role_str = f" [role: {role}]" if role else ""
            lines.append(f"  {cid}: {name}{role_str} -- {defn}")
            n += 1
    return "\n".join(lines), n


def _format_trace_excerpts(traces: list[Trace], cap_per_trace: int = 1200) -> str:
    if not traces:
        return "  (no recent trace evidence)"
    blocks = []
    for t in traces:
        # Pull the agent's actual text output rather than the whole transcript.
        text = ""
        for turn in t.transcript:
            if not isinstance(turn, dict):
                continue
            content = turn.get("content") or turn.get("text") or ""
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("text"):
                        text += item["text"] + "\n"
            elif isinstance(content, str):
                text += content + "\n"
        excerpt = text[:cap_per_trace]
        blocks.append(
            f"### {t.task_id}  [{t.final_gate_status}, repairs={t.repair_attempts_used}, outcome={t.outcome}]\n"
            f"evidence: {t.evidence[:300]}\n"
            f"transcript excerpt:\n{excerpt}"
        )
    return "\n\n".join(blocks)


def _llm_refine(prompt: str, *, model: str) -> Optional[dict[str, Any]]:
    """Single LLM call returning the refined taxonomy dict (JSON-parsed)."""
    if model.startswith("claude") or model.startswith("anthropic"):
        try:
            from anthropic import Anthropic
        except ImportError:
            logger.error("anthropic package not installed")
            return None
        client = Anthropic()
        msg = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
    else:
        try:
            from openai import OpenAI
        except ImportError:
            logger.error("openai package not installed")
            return None
        client = OpenAI()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Output ONLY valid JSON. No markdown fences."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=8192,
            temperature=0.3,
        )
        text = resp.choices[0].message.content or ""

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3].strip()
    if text.lower().startswith("json"):
        text = text[4:].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError as e:
                logger.error("refinement JSON parse failed: %s", e)
                return None
    return None


def _normalize(refined_raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten to category_a/b/c with stable IDs preserved."""
    annot: dict[str, Any] = {}
    for axis in ("category_a", "category_b", "category_c"):
        codes_in = refined_raw.get(axis, [])
        normed = []
        for c in codes_in:
            normed.append({
                "code": c.get("code") or c.get("id") or "",
                "name": c.get("name", ""),
                "definition": c.get("definition") or c.get("description", ""),
                "severity": c.get("severity", "major"),
                "applies_to_role": (c.get("applies_to_role") or c.get("role") or "").lower(),
            })
        annot[axis] = normed
    return {
        "annotation_layer": annot,
        "metadata": {"refined": True, "refinement_notes": refined_raw.get("refinement_notes", "")},
    }


def _compute_diff(old: dict[str, Any], new: dict[str, Any]) -> RefinementDiff:
    old_codes = _flatten(old)
    new_codes = _flatten(new)
    old_ids = set(old_codes.keys())
    new_ids = set(new_codes.keys())

    added = sorted(new_ids - old_ids)
    retired = sorted(old_ids - new_ids)
    sharpened: list[str] = []
    severity_changed: list[str] = []

    for cid in old_ids & new_ids:
        o = old_codes[cid]
        n = new_codes[cid]
        if (o.get("definition") or "").strip() != (n.get("definition") or "").strip():
            sharpened.append(cid)
        if (o.get("severity") or "") != (n.get("severity") or ""):
            severity_changed.append(cid)

    return RefinementDiff(
        added=added,
        retired=retired,
        sharpened=sorted(sharpened),
        severity_changed=sorted(severity_changed),
        notes=new.get("metadata", {}).get("refinement_notes", ""),
    )


def _flatten(taxonomy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    annot = taxonomy.get("annotation_layer", taxonomy)
    for axis in ("category_a", "category_b", "category_c"):
        for c in annot.get(axis, []):
            cid = c.get("code") or c.get("id")
            if cid:
                out[cid] = c
    return out


def refine(
    current: dict[str, Any],
    recent_traces: list[Trace],
    *,
    model: str = DEFAULT_REFINER_MODEL,
    iterations_since_last: Optional[int] = None,
) -> RefinementResult:
    """Refine an existing induced taxonomy against recent trace evidence."""
    if not current:
        return RefinementResult(taxonomy=None, diff=None,
                                reason="no current taxonomy to refine")

    existing_str, n_codes = _format_existing_codes(current)
    excerpts = _format_trace_excerpts(recent_traces)
    iters = iterations_since_last if iterations_since_last is not None else len(recent_traces)

    prompt = REFINEMENT_PROMPT.format(
        iterations=iters,
        n_codes=n_codes,
        existing_codes=existing_str,
        n_traces=len(recent_traces),
        trace_excerpts=excerpts,
    )
    raw = _llm_refine(prompt, model=model)
    if not raw:
        return RefinementResult(taxonomy=None, diff=None,
                                reason="refinement LLM call failed or returned non-JSON")

    refined = _normalize(raw)
    diff = _compute_diff(current, refined)
    return RefinementResult(
        taxonomy=refined,
        diff=diff,
        reason=(
            f"refined: +{len(diff.added)} -{len(diff.retired)} "
            f"sharpened={len(diff.sharpened)} severity_changes={len(diff.severity_changed)}"
        ),
    )
