"""Mapping Judge — failure_point + taxonomy -> best code(s).

A modular sub-judge that takes ONE already-identified failure point (no
trace reading, no causal analysis) and decides which taxonomy code(s)
best describe it. Useful when failure-point detection and code-assignment
are split across different stages or different models.

The Reflection Judge's two-call mode already performs this internally
(Stage 8). The Mapping Judge exposes the same logic as a standalone
primitive — call it directly when you have a failure point in hand
(from a stored Reflection Judge output, from a manual trace review, from
another system) and just need code assignments.

Public surface::

    judge = MappingJudge(taxonomy, judge_model="claude-sonnet-4-6")
    result = judge.run(failure_point_dict)

Result shape::

    MappingJudgeResult(
        primary_code="A.4" | None,
        secondary_codes=["B.2", ...],
        mapping_confidence=0.0..1.0,
        unmapped=bool,
        proposed_failure_mode={"name": "...", "definition": "..."} | None,
        ruled_out_codes=[{"code": "A.3", "reason": "..."}, ...],  # when unmapped
        judge_metadata={...},
    )

Policy mirrors the Reflection Judge's mapping stage: always try to map
an existing code first; ``unmapped=true`` is reserved for genuine
coverage gaps and requires both ``proposed_failure_mode`` and at least
one ``ruled_out_codes`` entry justifying the gap.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from atlas_runtime.learning_calls import judge_json
from atlas_runtime.taxonomy_data import Taxonomy

JudgeCallable = Callable[[str, str], Optional[str]]


# ──────────────────────────────────────────────────────────────────────────
# Result
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MappingJudgeResult:
    primary_code: Optional[str] = None
    secondary_codes: list[str] = field(default_factory=list)
    mapping_confidence: float = 0.0
    unmapped: bool = False
    proposed_failure_mode: Optional[dict[str, Any]] = None
    ruled_out_codes: list[dict[str, str]] = field(default_factory=list)
    judge_metadata: dict[str, Any] = field(default_factory=dict)

    def all_codes(self) -> list[str]:
        if not self.primary_code:
            return list(self.secondary_codes)
        return [self.primary_code, *self.secondary_codes]


# ──────────────────────────────────────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are the Mapping Judge. Given ONE already-identified failure point "
    "(a concrete failure observation with evidence — not a trace) and a "
    "failure-mode taxonomy catalog, assign the best taxonomy code(s).\n"
    "\n"
    "Policy:\n"
    "  * ALWAYS try to map an existing code first, even if the fit is "
    "partial. Set mapping_confidence to reflect the actual quality of the "
    "fit (0.7+ = good fit; 0.4-0.6 = stretched but plausible; <0.3 = poor).\n"
    "  * MULTIPLE codes are allowed when each describes a DIFFERENT aspect "
    "of the same failure. Pick ONE primary and zero or more secondary.\n"
    "  * ONLY set unmapped=true when you cannot find ANY taxonomy code that "
    "even partially applies. You MUST then provide:\n"
    "      ruled_out_codes: 2-3 closest existing codes with per-code reason;\n"
    "      proposed_failure_mode: {name, definition, detection_heuristics?}.\n"
    "  * When unmapped=false, primary_code MUST be set and proposed_failure_mode "
    "should be null.\n"
    "  * Return ONLY JSON in the user-prompt schema."
)


def user_prompt(failure_point: Mapping[str, Any], taxonomy_catalog: str) -> str:
    fp_text = json.dumps(dict(failure_point), indent=2, ensure_ascii=False)
    return f"""\
## FAILURE POINT
{fp_text}

## TAXONOMY CATALOG
{taxonomy_catalog}

## OUTPUT (JSON only)

{{
  "primary_code": "C.3",
  "secondary_codes": ["B.2"],
  "mapping_confidence": 0.85,
  "mapping_rationale": "why this fits",
  "unmapped": false,
  "ruled_out_codes": [],
  "proposed_failure_mode": null
}}

When ``unmapped=true``:

{{
  "primary_code": null,
  "secondary_codes": [],
  "mapping_confidence": 0.0,
  "unmapped": true,
  "ruled_out_codes": [
    {{"code": "C.5", "reason": "why this close code does not fit"}}
  ],
  "proposed_failure_mode": {{
    "name": "...",
    "definition": "...",
    "detection_heuristics": ["..."]
  }}
}}

Return ONLY the JSON object.
"""


# ──────────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────────


def validate_output(data: Mapping[str, Any], catalog_codes: set[str]) -> list[str]:
    errs: list[str] = []
    if not isinstance(data, Mapping):
        return ["root: output must be a JSON object"]

    unmapped = bool(data.get("unmapped", False))
    primary = data.get("primary_code")
    secondary = data.get("secondary_codes") or []
    proposed = data.get("proposed_failure_mode")
    ruled_out = data.get("ruled_out_codes") or []
    conf = data.get("mapping_confidence")

    if not isinstance(secondary, list):
        errs.append("secondary_codes: must be a list")
        secondary = []

    if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
        errs.append(f"mapping_confidence: {conf!r} must be a float in [0.0, 1.0]")

    if unmapped:
        if primary is not None:
            errs.append("unmapped=true: primary_code must be null")
        if secondary:
            errs.append("unmapped=true: secondary_codes must be []")
        if not isinstance(proposed, Mapping) or not proposed.get("name") \
                or not proposed.get("definition"):
            errs.append(
                "unmapped=true requires proposed_failure_mode: "
                "{name, definition, detection_heuristics?}"
            )
        if not isinstance(ruled_out, list) or len(ruled_out) < 1:
            errs.append(
                "unmapped=true requires non-empty ruled_out_codes "
                "(each entry: {code, reason})"
            )
        else:
            for i, r in enumerate(ruled_out):
                if not isinstance(r, Mapping) or not r.get("code") or not r.get("reason"):
                    errs.append(
                        f"ruled_out_codes[{i}]: must be {{code, reason}} with both set"
                    )
    else:
        if not isinstance(primary, str) or not primary.strip():
            errs.append("unmapped=false: primary_code must be a non-empty string")
        elif catalog_codes and primary not in catalog_codes:
            errs.append(f"primary_code: {primary!r} not in taxonomy catalog")
        for i, s in enumerate(secondary):
            if not isinstance(s, str):
                errs.append(f"secondary_codes[{i}]: must be a string")
            elif catalog_codes and s not in catalog_codes:
                errs.append(f"secondary_codes[{i}]: {s!r} not in taxonomy catalog")
            elif s == primary:
                errs.append(f"secondary_codes[{i}]: {s!r} is the primary code")

    return errs


# ──────────────────────────────────────────────────────────────────────────
# Judge class
# ──────────────────────────────────────────────────────────────────────────


class MappingJudge:
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

    def run(self, failure_point: Mapping[str, Any]) -> MappingJudgeResult:
        if not isinstance(failure_point, Mapping):
            raise TypeError("failure_point must be a mapping (dict)")

        prompt = user_prompt(failure_point, self._catalog)
        combined = f"{SYSTEM_PROMPT}\n\n{prompt}"
        warnings: list[str] = []

        raw = judge_json(combined, self.judge_model, max_retries=self.max_retries,
                         call=self.llm_call)
        if raw is None:
            warnings.append("judge_json returned None (LLM call failed or invalid JSON)")
            return MappingJudgeResult(judge_metadata=self._metadata(warnings))

        errs = validate_output(raw, self._catalog_codes)
        if errs:
            warnings.extend(errs[:5])

        # Salvage what we can. Treat severe shape errors as unmapped-with-no-proposal
        # rather than fabricating data.
        unmapped = bool(raw.get("unmapped", False))
        primary = raw.get("primary_code") if not unmapped else None
        if (
            primary is not None
            and not (
                isinstance(primary, str)
                and primary in self._catalog_codes
            )
        ):
            primary = None
        secondary = [
            s for s in (raw.get("secondary_codes") or [])
            if isinstance(s, str)
            and s in self._catalog_codes
            and s != primary
        ]
        conf = raw.get("mapping_confidence", 0.0)
        if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
            conf = 0.0

        proposed = raw.get("proposed_failure_mode") if unmapped else None
        ruled_out = [
            dict(r) for r in (raw.get("ruled_out_codes") or [])
            if isinstance(r, Mapping) and r.get("code") and r.get("reason")
        ] if unmapped else []

        return MappingJudgeResult(
            primary_code=primary,
            secondary_codes=secondary,
            mapping_confidence=float(conf),
            unmapped=unmapped,
            proposed_failure_mode=dict(proposed) if isinstance(proposed, Mapping) else None,
            ruled_out_codes=ruled_out,
            judge_metadata=self._metadata(warnings),
        )

    def _metadata(self, warnings: list[str]) -> dict[str, Any]:
        return {
            "judge": "mapping",
            "judge_model": self.judge_model,
            "taxonomy_version": self.taxonomy.version,
            "created_at": int(time.time()),
            "warnings": list(warnings),
        }


# ──────────────────────────────────────────────────────────────────────────
# Convenience
# ──────────────────────────────────────────────────────────────────────────


def run(
    failure_point: Mapping[str, Any],
    taxonomy: Taxonomy | Mapping[str, Any],
    *,
    judge_model: str,
    llm_call: Optional[JudgeCallable] = None,
) -> MappingJudgeResult:
    tax = taxonomy if isinstance(taxonomy, Taxonomy) else Taxonomy.from_flat(taxonomy)
    return MappingJudge(tax, judge_model=judge_model, llm_call=llm_call).run(failure_point)


__all__ = [
    "MappingJudge",
    "MappingJudgeResult",
    "SYSTEM_PROMPT",
    "user_prompt",
    "validate_output",
    "run",
]
