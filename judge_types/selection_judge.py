"""Selection Judge — trace + taxonomy -> flat failure-mode labels.

The Selection Judge answers one question per trace: *which taxonomy codes
fire here?* It does not build a causal graph (that's the Reflection
Judge's job); it just emits a flat list of fired codes with evidence and
a confidence tier. Cheap, batchable, consistent — designed for
selection / comparison / statistics use cases.

Public surface::

    judge = SelectionJudge(taxonomy, judge_model="claude-sonnet-4-6")
    result = judge.run(trace_text)               # one trace
    results = judge.run_many([t1, t2, t3])       # batched

Result shape::

    SelectionJudgeResult(
        failure_modes=[
            {"code": "A.3", "name": "...",
             "evidence": "<quote from trace>",
             "confidence": "high"|"medium"|"low",
             "severity": "minor"|"moderate"|"major"|"critical"},
            ...
        ],
        none_apply=bool,
        judge_metadata={...},
    )

Configurable: pass ``llm_call`` to inject a fake for tests. By default
the judge calls ``atlas_runtime.learning_calls.judge_json`` which already
does JSON repair-retry and routes to Anthropic / OpenAI / Gemini per the
model id (Bedrock-aware after issue #3).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from atlas_runtime.learning_calls import judge_json
from atlas_runtime.taxonomy_data import Taxonomy


# ──────────────────────────────────────────────────────────────────────────
# Enums + result shape
# ──────────────────────────────────────────────────────────────────────────

CONFIDENCE_TIERS = {"low", "medium", "high"}
SEVERITY_TIERS = {"minor", "moderate", "major", "critical"}

JudgeCallable = Callable[[str, str], Optional[str]]  # (prompt, model) -> raw text


@dataclass(frozen=True)
class SelectionJudgeResult:
    """One trace's Selection Judge verdict."""

    failure_modes: list[dict[str, Any]] = field(default_factory=list)
    none_apply: bool = False
    judge_metadata: dict[str, Any] = field(default_factory=dict)

    def code_ids(self) -> list[str]:
        return [m["code"] for m in self.failure_modes if m.get("code")]


# ──────────────────────────────────────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are the Selection Judge. Given an agent execution trace and a "
    "failure-mode taxonomy catalog, you identify which taxonomy codes fire "
    "in the trace. You produce a FLAT list of fired codes with evidence — "
    "no causal graph, no root-cause analysis, no recovery reasoning. The "
    "Reflection Judge handles depth; you handle breadth and speed.\n"
    "\n"
    "Policy:\n"
    "  * A code fires when the trace shows behavior matching its definition. "
    "Use the code's when_to_use and detection_heuristics as the bar.\n"
    "  * For each fired code, quote a specific span of the trace as evidence. "
    "Paraphrase only if the trace is too long to quote verbatim, and say so.\n"
    "  * Confidence is your certainty the code applies — high (clear match), "
    "medium (plausible), low (stretched).\n"
    "  * Severity is the code's intrinsic severity field; copy it unchanged.\n"
    "  * If NO code applies, return failure_modes=[] and none_apply=true.\n"
    "  * Return ONLY JSON in the user-prompt's schema. No prose."
)


def user_prompt(trace_text: str, taxonomy_catalog: str) -> str:
    """Render the Selection Judge user prompt for one trace."""
    return f"""\
## TAXONOMY CATALOG
{taxonomy_catalog}

## TRACE
{trace_text}

## OUTPUT (JSON only)

{{
  "failure_modes": [
    {{
      "code": "A.3",
      "name": "Premature termination",
      "evidence": "<quote or paraphrase from the trace>",
      "confidence": "high|medium|low",
      "severity": "minor|moderate|major|critical"
    }}
  ],
  "none_apply": false
}}

Rules:
  1. Every entry in failure_modes MUST have a non-empty evidence string.
  2. If you populate failure_modes, none_apply MUST be false.
  3. If none_apply is true, failure_modes MUST be [].
  4. Codes you choose MUST be present in the taxonomy catalog above.

Return ONLY the JSON object.
"""


# ──────────────────────────────────────────────────────────────────────────
# Output validation
# ──────────────────────────────────────────────────────────────────────────


def validate_output(data: Mapping[str, Any], catalog_codes: set[str]) -> list[str]:
    """Return a list of validation errors; empty list = valid."""
    errs: list[str] = []
    if not isinstance(data, Mapping):
        return ["root: output must be a JSON object"]

    modes = data.get("failure_modes")
    none_apply = bool(data.get("none_apply", False))

    if not isinstance(modes, list):
        errs.append("failure_modes: must be a list")
        modes = []

    if modes and none_apply:
        errs.append("none_apply=true requires failure_modes=[]")

    seen_codes: set[str] = set()
    for i, m in enumerate(modes):
        where = f"failure_modes[{i}]"
        if not isinstance(m, Mapping):
            errs.append(f"{where}: must be an object")
            continue
        code = m.get("code")
        if not isinstance(code, str) or not code.strip():
            errs.append(f"{where}.code: must be a non-empty string")
            continue
        if catalog_codes and code not in catalog_codes:
            errs.append(f"{where}.code: {code!r} not in taxonomy catalog")
        if code in seen_codes:
            errs.append(f"{where}.code: duplicate {code!r}")
        seen_codes.add(code)

        evidence = m.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            errs.append(f"{where}.evidence: must be a non-empty string")

        conf = m.get("confidence")
        if conf not in CONFIDENCE_TIERS:
            errs.append(
                f"{where}.confidence: {conf!r} not in {sorted(CONFIDENCE_TIERS)}"
            )

        sev = m.get("severity")
        if sev not in SEVERITY_TIERS:
            errs.append(f"{where}.severity: {sev!r} not in {sorted(SEVERITY_TIERS)}")

    return errs


# ──────────────────────────────────────────────────────────────────────────
# Judge class
# ──────────────────────────────────────────────────────────────────────────


class SelectionJudge:
    """Shallow per-trace classifier against a fixed taxonomy."""

    def __init__(
        self,
        taxonomy: Taxonomy,
        *,
        judge_model: str,
        llm_call: Optional[JudgeCallable] = None,
        max_retries: int = 1,
    ):
        if not judge_model:
            raise ValueError("judge_model is required")
        self.taxonomy = taxonomy
        self.judge_model = judge_model
        self.llm_call = llm_call
        self.max_retries = max_retries
        self._catalog = taxonomy.prompt_block()
        self._catalog_codes = {c.code for c in taxonomy.codes}

    def run(self, trace_text: str) -> SelectionJudgeResult:
        """Classify a single trace. Returns ``SelectionJudgeResult``."""
        prompt = user_prompt(trace_text, self._catalog)
        combined = f"{SYSTEM_PROMPT}\n\n{prompt}"
        warnings: list[str] = []

        raw = judge_json(combined, self.judge_model, max_retries=self.max_retries,
                         call=self.llm_call)
        if raw is None:
            warnings.append("judge_json returned None (LLM call failed or invalid JSON)")
            return SelectionJudgeResult(
                failure_modes=[], none_apply=False,
                judge_metadata=self._metadata(warnings),
            )

        errs = validate_output(raw, self._catalog_codes)
        if errs:
            warnings.extend(errs[:5])
            # Best-effort salvage: keep only well-shaped entries.
            modes = []
            for m in (raw.get("failure_modes") or []):
                if (
                    isinstance(m, Mapping)
                    and isinstance(m.get("code"), str)
                    and m.get("code") in self._catalog_codes
                    and isinstance(m.get("evidence"), str)
                    and m["evidence"].strip()
                ):
                    modes.append(dict(m))
        else:
            modes = [dict(m) for m in (raw.get("failure_modes") or [])]

        none_apply = bool(raw.get("none_apply", False)) and not modes
        if not modes and not none_apply:
            # The judge gave no codes AND didn't claim none_apply — surface
            # that as a warning rather than silently pretending one is set.
            warnings.append(
                "judge returned no failure_modes and did not set none_apply=true"
            )

        return SelectionJudgeResult(
            failure_modes=modes,
            none_apply=none_apply,
            judge_metadata=self._metadata(warnings),
        )

    def run_many(self, trace_texts: Sequence[str]) -> list[SelectionJudgeResult]:
        """Classify many traces. Sequential — no parallelism here so test
        stubs don't have to think about ordering. Wrap in ThreadPoolExecutor
        at the call site if you need parallel."""
        return [self.run(t) for t in trace_texts]

    def _metadata(self, warnings: list[str]) -> dict[str, Any]:
        return {
            "judge": "selection",
            "judge_model": self.judge_model,
            "taxonomy_version": self.taxonomy.version,
            "created_at": int(time.time()),
            "warnings": list(warnings),
        }


# ──────────────────────────────────────────────────────────────────────────
# Convenience function (matches the judge_types/ placeholder API)
# ──────────────────────────────────────────────────────────────────────────


def run(
    trace: Mapping[str, Any] | str,
    taxonomy: Taxonomy | Mapping[str, Any],
    *,
    judge_model: str,
    llm_call: Optional[JudgeCallable] = None,
) -> SelectionJudgeResult:
    """One-shot helper. Accepts either a trace dict (uses raw_trajectory)
    or a plain string. Accepts either a Taxonomy object or a flat
    candidate dict."""
    if isinstance(trace, Mapping):
        text = str(trace.get("raw_trajectory") or trace.get("task") or "")
    else:
        text = str(trace)
    tax = taxonomy if isinstance(taxonomy, Taxonomy) else Taxonomy.from_flat(taxonomy)
    judge = SelectionJudge(tax, judge_model=judge_model, llm_call=llm_call)
    return judge.run(text)


__all__ = [
    "CONFIDENCE_TIERS",
    "SEVERITY_TIERS",
    "SelectionJudge",
    "SelectionJudgeResult",
    "SYSTEM_PROMPT",
    "user_prompt",
    "validate_output",
    "run",
]
