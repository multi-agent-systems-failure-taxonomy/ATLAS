"""Reflection-shape validation owned by the Claude Code skin."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CodeAssignment:
    code_id: str
    evidence: str


@dataclass(frozen=True)
class ReflectionResult:
    checkpoint_id: str
    observe: str
    assignments: tuple[CodeAssignment, ...]
    considered_codes: tuple[str, ...]
    none_apply: bool
    correlate: str
    decide: str


_SECTION = re.compile(
    r"(?ims)^\s*(?:[-*]\s*)?"
    r"(Observe|Map|Correlate|Decide)\s*:\s*(.*?)"
    r"(?=^\s*(?:[-*]\s*)?(?:Observe|Map|Correlate|Decide)\s*:|\Z)"
)
_CHECKPOINT = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?Checkpoint\s+ID\s*:\s*([^\s]+)"
)
_EVIDENCE = re.compile(
    r"(?i)\bevidence\s*:\s*(?:\"([^\"]+)\"|'([^']+)'|(.+))"
)


def parse_reflection(
    text: str,
    *,
    checkpoint_id: str,
    known_code_ids: list[str] | tuple[str, ...],
) -> ReflectionResult:
    """Validate one Observe/Map/Correlate/Decide block.

    A valid Map either marks at least one known code as exhibited with evidence,
    or explicitly says none apply while naming at least one considered known
    code and giving evidence. The checker validates shape, not insight quality.
    """
    text = text or ""
    starts = [match.start() for match in re.finditer(
        r"(?im)^\s*ATLAS\s+reflection\s*:", text
    )]
    if not starts:
        raise ValueError("missing `ATLAS reflection:` block")
    block = text[starts[-1]:]
    marker = _CHECKPOINT.search(block)
    if not marker or marker.group(1).strip() != checkpoint_id:
        raise ValueError(
            f"reflection must include `Checkpoint ID: {checkpoint_id}`"
        )

    sections = {
        match.group(1).lower(): match.group(2).strip()
        for match in _SECTION.finditer(block)
    }
    for name in ("observe", "map", "correlate", "decide"):
        if not sections.get(name):
            raise ValueError(f"reflection has an empty or missing {name.title()} step")

    known = {str(code_id) for code_id in known_code_ids}
    map_text = sections["map"]
    mentioned = tuple(
        code_id
        for code_id in known_code_ids
        if re.search(
            rf"(?<![A-Za-z0-9_.-]){re.escape(str(code_id))}"
            rf"(?![A-Za-z0-9_.-])",
            map_text,
            re.IGNORECASE,
        )
    )
    if not mentioned:
        raise ValueError("Map must name at least one active taxonomy code")

    none_apply = bool(re.search(r"\bnone\s+appl(?:y|ies)\b", map_text, re.I))
    assignments: list[CodeAssignment] = []
    for line in map_text.splitlines():
        if not re.search(r"\b(?:exhibited|fired|applies)\b", line, re.I):
            continue
        if re.search(r"\b(?:not[- ]exhibited|not[- ]fired|does not apply)\b", line, re.I):
            continue
        evidence = _evidence(line)
        for code_id in known:
            if re.search(
                rf"(?<![A-Za-z0-9_.-]){re.escape(code_id)}"
                rf"(?![A-Za-z0-9_.-])",
                line,
                re.I,
            ):
                if not evidence:
                    raise ValueError(
                        f"exhibited code {code_id!r} must include evidence"
                    )
                assignments.append(CodeAssignment(code_id, evidence))

    if none_apply:
        if assignments:
            raise ValueError("Map cannot both fire codes and say none apply")
        if not _evidence(map_text):
            raise ValueError("`none apply` must include evidence or a reason")
    elif not assignments:
        raise ValueError(
            "Map must fire a code with evidence or explicitly say none apply"
        )

    decide = sections["decide"]
    valid_decision = (
        re.search(r"\bchange\s*:", decide, re.I)
        or re.search(r"\bno\s+change\s+needed\b", decide, re.I)
    )
    if not valid_decision:
        raise ValueError(
            "Decide must contain `change: ...` or `no change needed, because ...`"
        )
    if re.search(r"\bno\s+change\s+needed\b", decide, re.I) and not re.search(
        r"\bbecause\b", decide, re.I
    ):
        raise ValueError("`no change needed` must include a reason")

    return ReflectionResult(
        checkpoint_id=checkpoint_id,
        observe=sections["observe"],
        assignments=tuple(assignments),
        considered_codes=tuple(str(item) for item in mentioned),
        none_apply=none_apply,
        correlate=sections["correlate"],
        decide=decide,
    )


def _evidence(text: str) -> str:
    match = _EVIDENCE.search(text)
    if not match:
        because = re.search(r"(?i)\bbecause\b\s*(.+)", text)
        return because.group(1).strip() if because else ""
    return next(
        (group.strip() for group in match.groups() if group and group.strip()),
        "",
    )
