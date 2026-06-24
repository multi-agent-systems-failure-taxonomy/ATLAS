"""Coverage / Discovery Judge — does the taxonomy cover this failure?

Per-trace (or per-failure-point) coverage assessment. Asks: given the
current taxonomy, is the observed failure pattern already covered? Just
partially? Not at all? If partial or missing, name the closest existing
code(s) and propose what a new code might look like.

Used to drive taxonomy expansion BEFORE a full Reflection Judge + refiner
pass — cheaper than full reflection when you just need a yes/no/proposal
on a specific input.

Public surface::

    judge = CoverageJudge(taxonomy, judge_model="claude-sonnet-4-6")
    result = judge.run({"trace": "...", "failure_point": {...}})

At least one of ``trace`` or ``failure_point`` must be provided. Both
together is allowed — the judge will use the failure point as the focus
and the trace as supporting context.

Result shape::

    CoverageJudgeResult(
        coverage_status="covered" | "partially_covered" | "not_covered",
        closest_codes=["A.3", "B.1"],
        missing_failure_pattern="<one-line description>" | None,
        suggest_new_code=bool,
        proposed_failure_mode={"name", "definition", "detection_heuristics"} | None,
        judge_metadata={...},
    )
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from atlas_runtime.learning_calls import judge_json
from atlas_runtime.taxonomy_data import Taxonomy

JudgeCallable = Callable[[str, str], Optional[str]]

COVERAGE_STATUSES = {"covered", "partially_covered", "not_covered"}


# ──────────────────────────────────────────────────────────────────────────
# Result
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CoverageJudgeResult:
    coverage_status: str = "not_covered"
    closest_codes: list[str] = field(default_factory=list)
    missing_failure_pattern: Optional[str] = None
    suggest_new_code: bool = False
    proposed_failure_mode: Optional[dict[str, Any]] = None
    judge_metadata: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are the Coverage Judge. Given an agent execution observation (a "
    "trace, a specific failure point, or both) and a failure-mode taxonomy "
    "catalog, you decide whether the current taxonomy ALREADY covers the "
    "observed failure pattern.\n"
    "\n"
    "Output is one of three coverage statuses:\n"
    "  * covered           - at least one existing code is a strong fit;\n"
    "  * partially_covered - one or more codes are related but each misses "
    "an important aspect of the observed pattern;\n"
    "  * not_covered       - no existing code is even a partial fit.\n"
    "\n"
    "When status is partially_covered or not_covered, name the CLOSEST "
    "existing codes (closest_codes) and describe the missing failure pattern "
    "in one sentence (missing_failure_pattern). If a new code is warranted, "
    "set suggest_new_code=true and fill proposed_failure_mode with a name + "
    "definition + detection_heuristics in the taxonomy style.\n"
    "\n"
    "When status is covered, closest_codes lists the matching code(s), "
    "missing_failure_pattern is null, and suggest_new_code is false.\n"
    "\n"
    "Return ONLY JSON in the user-prompt schema."
)


def user_prompt(payload: Mapping[str, Any], taxonomy_catalog: str) -> str:
    trace = str(payload.get("trace") or "").strip()
    failure_point = payload.get("failure_point")
    fp_text = (
        json.dumps(dict(failure_point), indent=2, ensure_ascii=False)
        if isinstance(failure_point, Mapping)
        else "(not provided)"
    )
    trace_text = trace if trace else "(not provided)"
    return f"""\
## TAXONOMY CATALOG
{taxonomy_catalog}

## OBSERVATION

### failure_point
{fp_text}

### trace (supporting context)
{trace_text}

## OUTPUT (JSON only)

{{
  "coverage_status": "covered | partially_covered | not_covered",
  "closest_codes": ["A.3", "B.1"],
  "missing_failure_pattern": "one-sentence description of what is not captured (or null)",
  "suggest_new_code": false,
  "proposed_failure_mode": null
}}

Rules:
  1. coverage_status MUST be one of: covered, partially_covered, not_covered.
  2. closest_codes MUST reference codes present in the taxonomy catalog above.
  3. If coverage_status is "covered", missing_failure_pattern MUST be null
     and suggest_new_code MUST be false.
  4. If suggest_new_code is true, proposed_failure_mode MUST be a non-null
     object with name + definition (detection_heuristics optional).

Return ONLY the JSON object.
"""


# ──────────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────────


def validate_output(data: Mapping[str, Any], catalog_codes: set[str]) -> list[str]:
    errs: list[str] = []
    if not isinstance(data, Mapping):
        return ["root: output must be a JSON object"]

    status = data.get("coverage_status")
    if status not in COVERAGE_STATUSES:
        errs.append(
            f"coverage_status: {status!r} not in {sorted(COVERAGE_STATUSES)}"
        )

    closest = data.get("closest_codes") or []
    if not isinstance(closest, list):
        errs.append("closest_codes: must be a list")
        closest = []
    for i, c in enumerate(closest):
        if not isinstance(c, str):
            errs.append(f"closest_codes[{i}]: must be a string")
        elif catalog_codes and c not in catalog_codes:
            errs.append(f"closest_codes[{i}]: {c!r} not in taxonomy catalog")

    suggest = bool(data.get("suggest_new_code", False))
    proposed = data.get("proposed_failure_mode")
    missing = data.get("missing_failure_pattern")

    if status == "covered":
        if missing not in (None, ""):
            errs.append("coverage_status=covered: missing_failure_pattern must be null")
        if suggest:
            errs.append("coverage_status=covered: suggest_new_code must be false")

    if suggest:
        if not isinstance(proposed, Mapping) or not proposed.get("name") \
                or not proposed.get("definition"):
            errs.append(
                "suggest_new_code=true requires proposed_failure_mode "
                "{name, definition, detection_heuristics?}"
            )

    return errs


# ──────────────────────────────────────────────────────────────────────────
# Judge class
# ──────────────────────────────────────────────────────────────────────────


class CoverageJudge:
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

    def run(self, payload: Mapping[str, Any]) -> CoverageJudgeResult:
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping (dict)")
        if not payload.get("trace") and not isinstance(payload.get("failure_point"), Mapping):
            raise ValueError(
                "payload must contain at least one of: trace (str) or "
                "failure_point (dict)"
            )

        prompt = user_prompt(payload, self._catalog)
        combined = f"{SYSTEM_PROMPT}\n\n{prompt}"
        warnings: list[str] = []

        raw = judge_json(combined, self.judge_model, max_retries=self.max_retries,
                         call=self.llm_call)
        if raw is None:
            warnings.append("judge_json returned None (LLM call failed or invalid JSON)")
            return CoverageJudgeResult(judge_metadata=self._metadata(warnings))

        errs = validate_output(raw, self._catalog_codes)
        if errs:
            warnings.extend(errs[:5])

        status = raw.get("coverage_status")
        if status not in COVERAGE_STATUSES:
            status = "not_covered"
        closest = [
            c for c in (raw.get("closest_codes") or [])
            if isinstance(c, str) and c in self._catalog_codes
        ]
        missing = raw.get("missing_failure_pattern")
        if not isinstance(missing, str):
            missing = None
        suggest = bool(raw.get("suggest_new_code", False))
        proposed = raw.get("proposed_failure_mode")
        if not (isinstance(proposed, Mapping) and proposed.get("name") and proposed.get("definition")):
            proposed = None
            if suggest:
                suggest = False  # don't claim a proposal that isn't there

        return CoverageJudgeResult(
            coverage_status=status,
            closest_codes=closest,
            missing_failure_pattern=missing,
            suggest_new_code=suggest,
            proposed_failure_mode=dict(proposed) if proposed else None,
            judge_metadata=self._metadata(warnings),
        )

    def _metadata(self, warnings: list[str]) -> dict[str, Any]:
        return {
            "judge": "coverage",
            "judge_model": self.judge_model,
            "taxonomy_version": self.taxonomy.version,
            "created_at": int(time.time()),
            "warnings": list(warnings),
        }


# ──────────────────────────────────────────────────────────────────────────
# Convenience
# ──────────────────────────────────────────────────────────────────────────


def run(
    payload: Mapping[str, Any],
    taxonomy: Taxonomy | Mapping[str, Any],
    *,
    judge_model: str,
    llm_call: Optional[JudgeCallable] = None,
) -> CoverageJudgeResult:
    tax = taxonomy if isinstance(taxonomy, Taxonomy) else Taxonomy.from_flat(taxonomy)
    return CoverageJudge(tax, judge_model=judge_model, llm_call=llm_call).run(payload)


__all__ = [
    "COVERAGE_STATUSES",
    "CoverageJudge",
    "CoverageJudgeResult",
    "SYSTEM_PROMPT",
    "user_prompt",
    "validate_output",
    "run",
]
