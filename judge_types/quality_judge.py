"""Taxonomy Quality Judge — evaluate the taxonomy itself.

This judge does NOT score traces. It scores the codebook. Per code, it
asks: is this code observable, distinct, neither too broad nor too narrow,
clearly defined? Across the set, is there redundancy / overlap / obvious
gaps? Returns per-code issues + recommendations and an overall verdict.

Optionally accepts support traces — when supplied, the judge can ground
recommendations in concrete evidence ("this code never fires on the
support set"). Without support traces, it works on definitional grounds
alone (overlap, clarity, observability).

Public surface::

    judge = QualityJudge(taxonomy, judge_model="claude-sonnet-4-6")
    result = judge.run()                                 # definition-only
    result = judge.run(support_traces=["...", "..."])    # grounded

Result shape::

    QualityJudgeResult(
        code_quality=[
            {"code": "A.3",
             "issue": "overlaps with A.5 in 80% of detection heuristics",
             "recommendation": "merge into A.5 or split premature termination"},
            ...
        ],
        overall_quality="good" | "needs_refinement" | "poor",
        overall_summary="...",
        judge_metadata={...},
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from atlas_runtime.learning_calls import judge_json
from atlas_runtime.taxonomy_data import Taxonomy

JudgeCallable = Callable[[str, str], Optional[str]]

OVERALL_QUALITIES = {"good", "needs_refinement", "poor"}


# ──────────────────────────────────────────────────────────────────────────
# Result
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QualityJudgeResult:
    code_quality: list[dict[str, Any]] = field(default_factory=list)
    overall_quality: str = "needs_refinement"
    overall_summary: str = ""
    judge_metadata: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are the Taxonomy Quality Judge. You evaluate a failure-mode "
    "taxonomy as a WHOLE: are the codes observable, distinct, "
    "appropriately scoped, and clearly defined? You do NOT classify "
    "traces against the taxonomy — you score the taxonomy itself.\n"
    "\n"
    "For each code, decide whether it has a quality issue. Common issues:\n"
    "  * not observable in traces (definition too abstract);\n"
    "  * overlaps with another code (redundant or partially redundant);\n"
    "  * too broad (catches genuinely different patterns);\n"
    "  * too narrow (rarely or never fires);\n"
    "  * definition is unclear or self-contradictory;\n"
    "  * detection_heuristics don't actually help judges discriminate.\n"
    "\n"
    "If support traces are provided, USE them — a code that never fires on "
    "the support set is concrete evidence of being too narrow or unused. "
    "Without support traces, work on definitional grounds alone.\n"
    "\n"
    "Only emit code_quality entries for codes WITH an issue. Codes that "
    "are fine should be omitted. Set overall_quality based on how many "
    "and how severe the issues are.\n"
    "\n"
    "Return ONLY JSON in the user-prompt schema."
)


def user_prompt(taxonomy_catalog: str, support_traces: Sequence[str] | None = None) -> str:
    if support_traces:
        traces_block = "\n\n---\n\n".join(
            f"### support trace {i+1}\n{t}"
            for i, t in enumerate(support_traces)
        )
        traces_section = f"## SUPPORT TRACES\n{traces_block}\n\n"
    else:
        traces_section = "## SUPPORT TRACES\n(none provided; evaluate on definitional grounds alone)\n\n"

    return f"""\
## TAXONOMY CATALOG
{taxonomy_catalog}

{traces_section}## OUTPUT (JSON only)

{{
  "code_quality": [
    {{
      "code": "A.3",
      "issue": "overlaps with A.5 in detection heuristics; both fire on the same evidence",
      "recommendation": "merge A.3 into A.5, OR sharpen A.3 to cover only premature termination not invalid finalization"
    }}
  ],
  "overall_quality": "good | needs_refinement | poor",
  "overall_summary": "one-paragraph summary of taxonomy health"
}}

Rules:
  1. Only include codes WITH a real issue. Healthy codes get omitted.
  2. Codes you reference MUST be present in the taxonomy catalog above.
  3. overall_quality MUST be one of: good, needs_refinement, poor.
  4. overall_summary MUST be a non-empty string explaining the verdict.

Return ONLY the JSON object.
"""


# ──────────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────────


def validate_output(data: Mapping[str, Any], catalog_codes: set[str]) -> list[str]:
    errs: list[str] = []
    if not isinstance(data, Mapping):
        return ["root: output must be a JSON object"]

    code_quality = data.get("code_quality") or []
    if not isinstance(code_quality, list):
        errs.append("code_quality: must be a list")
        code_quality = []

    seen = set()
    for i, item in enumerate(code_quality):
        where = f"code_quality[{i}]"
        if not isinstance(item, Mapping):
            errs.append(f"{where}: must be an object")
            continue
        code = item.get("code")
        if not isinstance(code, str) or not code.strip():
            errs.append(f"{where}.code: must be a non-empty string")
            continue
        if catalog_codes and code not in catalog_codes:
            errs.append(f"{where}.code: {code!r} not in taxonomy catalog")
        if code in seen:
            errs.append(f"{where}.code: duplicate {code!r}")
        seen.add(code)
        for required in ("issue", "recommendation"):
            v = item.get(required)
            if not isinstance(v, str) or not v.strip():
                errs.append(f"{where}.{required}: must be a non-empty string")

    overall = data.get("overall_quality")
    if overall not in OVERALL_QUALITIES:
        errs.append(f"overall_quality: {overall!r} not in {sorted(OVERALL_QUALITIES)}")

    summary = data.get("overall_summary")
    if not isinstance(summary, str) or not summary.strip():
        errs.append("overall_summary: must be a non-empty string")

    return errs


# ──────────────────────────────────────────────────────────────────────────
# Judge class
# ──────────────────────────────────────────────────────────────────────────


class QualityJudge:
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

    def run(
        self,
        support_traces: Sequence[str] | None = None,
    ) -> QualityJudgeResult:
        prompt = user_prompt(self._catalog, support_traces)
        combined = f"{SYSTEM_PROMPT}\n\n{prompt}"
        warnings: list[str] = []

        raw = judge_json(combined, self.judge_model, max_retries=self.max_retries,
                         call=self.llm_call)
        if raw is None:
            warnings.append("judge_json returned None (LLM call failed or invalid JSON)")
            return QualityJudgeResult(judge_metadata=self._metadata(warnings))

        errs = validate_output(raw, self._catalog_codes)
        if errs:
            warnings.extend(errs[:5])

        # Salvage: keep only well-formed code_quality entries.
        kept: list[dict[str, Any]] = []
        for item in (raw.get("code_quality") or []):
            if not isinstance(item, Mapping):
                continue
            code = item.get("code")
            if not (isinstance(code, str) and code in self._catalog_codes):
                continue
            if not (
                isinstance(item.get("issue"), str)
                and item["issue"].strip()
                and isinstance(item.get("recommendation"), str)
                and item["recommendation"].strip()
            ):
                continue
            kept.append(dict(item))

        overall = raw.get("overall_quality")
        if overall not in OVERALL_QUALITIES:
            overall = "needs_refinement"
        summary = raw.get("overall_summary")
        if not isinstance(summary, str):
            summary = ""

        return QualityJudgeResult(
            code_quality=kept,
            overall_quality=overall,
            overall_summary=summary,
            judge_metadata=self._metadata(warnings),
        )

    def _metadata(self, warnings: list[str]) -> dict[str, Any]:
        return {
            "judge": "quality",
            "judge_model": self.judge_model,
            "taxonomy_version": self.taxonomy.version,
            "created_at": int(time.time()),
            "warnings": list(warnings),
        }


# ──────────────────────────────────────────────────────────────────────────
# Convenience
# ──────────────────────────────────────────────────────────────────────────


def run(
    taxonomy: Taxonomy | Mapping[str, Any],
    *,
    judge_model: str,
    support_traces: Sequence[str] | None = None,
    llm_call: Optional[JudgeCallable] = None,
) -> QualityJudgeResult:
    tax = taxonomy if isinstance(taxonomy, Taxonomy) else Taxonomy.from_flat(taxonomy)
    return QualityJudge(tax, judge_model=judge_model, llm_call=llm_call).run(support_traces)


__all__ = [
    "OVERALL_QUALITIES",
    "QualityJudge",
    "QualityJudgeResult",
    "SYSTEM_PROMPT",
    "user_prompt",
    "validate_output",
    "run",
]
