"""Calibration / Agreement Judge — is this code assignment reliable?

Audits a Selection Judge (or human) annotation against the underlying
evidence and the taxonomy code definition. Per annotation, asks:

  * Does the cited evidence actually support the assigned code?
  * Is the confidence level calibrated (the annotation says "high" but
    the evidence reads "weak")?
  * Are there other codes that would have fit equally well or better?
  * Does the pattern look like an over-trigger (this code is too easy
    to fire — likely an over-broad definition)?

Used to spot-check Selection Judge outputs in CI, to flag systematic
over- or under-triggering of specific codes, and to surface low-quality
annotations before they propagate into refinement signals.

Public surface::

    judge = CalibrationJudge(taxonomy, judge_model="claude-sonnet-4-6")
    result = judge.run({
        "annotation": {"code": "A.3", "confidence": "high"},
        "evidence": "<the quote that was cited>",
    })

Result shape::

    CalibrationJudgeResult(
        annotation_valid=bool,
        evidence_support="strong" | "moderate" | "weak" | "none",
        possible_overtrigger=bool,
        conflicting_codes=["A.5", "B.2"],
        rationale="...",
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

EVIDENCE_SUPPORT = {"strong", "moderate", "weak", "none"}


# ──────────────────────────────────────────────────────────────────────────
# Result
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CalibrationJudgeResult:
    annotation_valid: bool = False
    evidence_support: str = "none"
    possible_overtrigger: bool = False
    conflicting_codes: list[str] = field(default_factory=list)
    rationale: str = ""
    judge_metadata: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are the Calibration Judge. You audit a single taxonomy-code "
    "annotation against the underlying evidence and the taxonomy's "
    "definition of that code. You decide whether the annotation is "
    "reliable.\n"
    "\n"
    "Process:\n"
    "  1. Read the code's full spec from the taxonomy (definition, "
    "when_to_use, when_not_to_use, detection_heuristics).\n"
    "  2. Read the evidence the annotator cited.\n"
    "  3. Decide evidence_support: strong (evidence clearly satisfies the "
    "code's bar) / moderate (plausible) / weak (stretched) / none (the "
    "evidence does not support the code at all).\n"
    "  4. Set annotation_valid=true ONLY if evidence_support is "
    "strong OR moderate AND the cited confidence is consistent with the "
    "evidence (high confidence requires strong evidence).\n"
    "  5. Scan the rest of the catalog. List any codes that would have "
    "fit EQUALLY WELL OR BETTER (conflicting_codes). If the annotated "
    "code fires on weak evidence AND several others would also fire, "
    "the code is likely over-broad — set possible_overtrigger=true.\n"
    "  6. Give a one-paragraph rationale explaining the verdict.\n"
    "\n"
    "Return ONLY JSON in the user-prompt schema."
)


def user_prompt(
    annotation: Mapping[str, Any],
    evidence: str,
    taxonomy_catalog: str,
) -> str:
    annotation_text = json.dumps(dict(annotation), indent=2, ensure_ascii=False)
    return f"""\
## TAXONOMY CATALOG
{taxonomy_catalog}

## ANNOTATION TO AUDIT
{annotation_text}

## CITED EVIDENCE
{evidence}

## OUTPUT (JSON only)

{{
  "annotation_valid": true,
  "evidence_support": "strong | moderate | weak | none",
  "possible_overtrigger": false,
  "conflicting_codes": ["A.5"],
  "rationale": "one paragraph explaining the verdict"
}}

Rules:
  1. evidence_support MUST be one of: strong, moderate, weak, none.
  2. annotation_valid=true requires evidence_support in (strong, moderate).
  3. conflicting_codes MUST reference codes present in the taxonomy catalog.
  4. rationale MUST be a non-empty string.

Return ONLY the JSON object.
"""


# ──────────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────────


def validate_output(data: Mapping[str, Any], catalog_codes: set[str]) -> list[str]:
    errs: list[str] = []
    if not isinstance(data, Mapping):
        return ["root: output must be a JSON object"]

    support = data.get("evidence_support")
    if support not in EVIDENCE_SUPPORT:
        errs.append(
            f"evidence_support: {support!r} not in {sorted(EVIDENCE_SUPPORT)}"
        )

    valid = data.get("annotation_valid")
    if not isinstance(valid, bool):
        errs.append(f"annotation_valid: {valid!r} must be a bool")
    elif valid and support not in ("strong", "moderate"):
        errs.append(
            f"annotation_valid=true requires evidence_support in "
            f"('strong','moderate') (got {support!r})"
        )

    overtrigger = data.get("possible_overtrigger")
    if not isinstance(overtrigger, bool):
        errs.append(f"possible_overtrigger: {overtrigger!r} must be a bool")

    conflicting = data.get("conflicting_codes") or []
    if not isinstance(conflicting, list):
        errs.append("conflicting_codes: must be a list")
        conflicting = []
    for i, c in enumerate(conflicting):
        if not isinstance(c, str):
            errs.append(f"conflicting_codes[{i}]: must be a string")
        elif catalog_codes and c not in catalog_codes:
            errs.append(f"conflicting_codes[{i}]: {c!r} not in taxonomy catalog")

    rationale = data.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        errs.append("rationale: must be a non-empty string")

    return errs


# ──────────────────────────────────────────────────────────────────────────
# Judge class
# ──────────────────────────────────────────────────────────────────────────


class CalibrationJudge:
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

    def run(self, payload: Mapping[str, Any]) -> CalibrationJudgeResult:
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping (dict)")
        annotation = payload.get("annotation")
        if not isinstance(annotation, Mapping) or not annotation.get("code"):
            raise ValueError(
                "payload.annotation must be a dict with at least a 'code' field"
            )
        evidence = payload.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("payload.evidence must be a non-empty string")
        annotated_code = annotation["code"]
        if annotated_code not in self._catalog_codes:
            raise ValueError(
                f"annotation.code={annotated_code!r} not in taxonomy catalog "
                f"(known codes: {sorted(self._catalog_codes)})"
            )

        prompt = user_prompt(annotation, evidence, self._catalog)
        combined = f"{SYSTEM_PROMPT}\n\n{prompt}"
        warnings: list[str] = []

        raw = judge_json(combined, self.judge_model, max_retries=self.max_retries,
                         call=self.llm_call)
        if raw is None:
            warnings.append("judge_json returned None (LLM call failed or invalid JSON)")
            return CalibrationJudgeResult(judge_metadata=self._metadata(warnings))

        errs = validate_output(raw, self._catalog_codes)
        if errs:
            warnings.extend(errs[:5])

        support = raw.get("evidence_support")
        if support not in EVIDENCE_SUPPORT:
            support = "none"
        valid = bool(raw.get("annotation_valid", False))
        # Enforce the consistency rule even if the LLM violated it.
        if valid and support not in ("strong", "moderate"):
            valid = False
            warnings.append(
                f"forcing annotation_valid=false (evidence_support={support!r})"
            )
        overtrigger = bool(raw.get("possible_overtrigger", False))
        conflicting = [
            c for c in (raw.get("conflicting_codes") or [])
            if isinstance(c, str) and c in self._catalog_codes and c != annotated_code
        ]
        rationale = raw.get("rationale")
        if not isinstance(rationale, str):
            rationale = ""

        return CalibrationJudgeResult(
            annotation_valid=valid,
            evidence_support=support,
            possible_overtrigger=overtrigger,
            conflicting_codes=conflicting,
            rationale=rationale,
            judge_metadata=self._metadata(warnings),
        )

    def _metadata(self, warnings: list[str]) -> dict[str, Any]:
        return {
            "judge": "calibration",
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
) -> CalibrationJudgeResult:
    tax = taxonomy if isinstance(taxonomy, Taxonomy) else Taxonomy.from_flat(taxonomy)
    return CalibrationJudge(tax, judge_model=judge_model, llm_call=llm_call).run(payload)


__all__ = [
    "EVIDENCE_SUPPORT",
    "CalibrationJudge",
    "CalibrationJudgeResult",
    "SYSTEM_PROMPT",
    "user_prompt",
    "validate_output",
    "run",
]
