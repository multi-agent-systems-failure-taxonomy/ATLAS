"""Shared ATLAS reflection parsing and result types."""

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
    r"(?ims)^[ \t]*[#>*\-]*[ \t]*\**[ \t]*"
    r"(Observe|Observation|Review|Map|Mapping|"
    r"Correlate|Root[ \t]*causes?|Causal|Decide|Decision|Action)"
    r"[ \t]*:?[ \t]*\**[ \t]*(.*?)"
    r"(?=^[ \t]*[#>*\-]*[ \t]*\**[ \t]*"
    r"(?:Observe|Observation|Review|Map|Mapping|"
    r"Correlate|Root[ \t]*causes?|Causal|Decide|Decision|Action)\b|\Z)"
)
_CHECKPOINT = re.compile(
    r"(?im)^\s*(?:[#>*-]\s*)*\**\s*Checkpoint\s+ID\s*:\s*([^\s*]+)"
)
_EVIDENCE = re.compile(
    r"(?i)\bevidence\s*[:\-–—]\s*(?:\"([^\"]+)\"|'([^']+)'|(.+))"
)

_EVIDENCE = re.compile(
    r"(?i)\bevidence\s*(?:[:=\-–—]|\bis\b)\s*"
    r"(?:\"([^\"]+)\"|'([^']+)'|(.+))"
)


def _canon_section(name: str) -> str:
    normalized = " ".join(name.strip().lower().split())
    if normalized in {"observation", "review"}:
        return "observe"
    if normalized == "mapping":
        return "map"
    if normalized.startswith("root cause") or normalized == "causal":
        return "correlate"
    if normalized in {"decision", "action"}:
        return "decide"
    return normalized


def parse_reflection(
    text: str,
    *,
    checkpoint_id: str,
    known_code_ids: list[str] | tuple[str, ...],
) -> ReflectionResult:
    """Validate one Observe/Map/Correlate/Decide block.

    A valid Map either names at least one known code with evidence, or
    explicitly says none apply while naming at least one considered known code
    and giving evidence. The checker validates shape, not insight quality.
    """
    text = text or ""
    starts = [
        match.start()
        for match in re.finditer(
            r"(?im)^[ \t]*#*[ \t]*\**[ \t]*ATLAS\s+reflection\b",
            text,
        )
    ]
    if not starts:
        raise ValueError("missing `ATLAS reflection` block")
    block = text[starts[-1]:]
    marker = _CHECKPOINT.search(block)
    if not marker or marker.group(1).strip() != checkpoint_id:
        raise ValueError(
            f"reflection must include `Checkpoint ID: {checkpoint_id}`"
        )

    sections = {
        _canon_section(match.group(1)): match.group(2).strip()
        for match in _SECTION.finditer(block)
    }
    for name in ("observe", "map", "correlate", "decide"):
        if not sections.get(name):
            raise ValueError(f"reflection has an empty or missing {name.title()} step")

    known = tuple(str(code_id) for code_id in known_code_ids)
    map_text = sections["map"]
    negated_or_clean = re.compile(
        r"none\s+appl|\bconsidered\b|not[\s-]+(?:exhibit|fire|appl)|"
        r"does\s+not\s+apply|doesn'?t\s+apply|\bn/?a\b|no\s+failure|"
        r"\bclean\b|not\s+present|\babsent\b",
        re.I,
    )
    mentioned = _mentioned_codes(map_text, known)
    assignments: list[CodeAssignment] = []
    seen: set[str] = set()
    for line in map_text.splitlines():
        if not line.strip():
            continue
        evidence_match = _EVIDENCE.search(line)
        prefix = line[: evidence_match.start()] if evidence_match else line
        if negated_or_clean.search(prefix):
            continue
        evidence = _evidence(line)
        if not evidence:
            continue
        for code_id in known:
            if code_id in seen:
                continue
            if re.search(
                rf"(?<![A-Za-z0-9_.-]){re.escape(code_id)}"
                rf"(?![A-Za-z0-9_.-])",
                line,
                re.I,
            ):
                assignments.append(CodeAssignment(code_id, evidence))
                seen.add(code_id)

    none_apply = (not assignments) and bool(
        re.search(r"\bnone\s+appl(?:y|ies)\b", map_text, re.I)
    )
    if none_apply and not mentioned:
        mentioned = _mentioned_codes(block, known)
    if not mentioned:
        raise ValueError("Map must name at least one active taxonomy code")
    if none_apply and not _evidence(map_text):
        raise ValueError("`none apply` must include evidence or a reason")
    if not assignments and not none_apply:
        raise ValueError(
            "Map must fire a code (id + evidence) or explicitly say none apply"
        )

    decide = sections["decide"]
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


def _mentioned_codes(text: str, known: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        code_id
        for code_id in known
        if re.search(
            rf"(?<![A-Za-z0-9_.-]){re.escape(code_id)}"
            rf"(?![A-Za-z0-9_.-])",
            text,
            re.IGNORECASE,
        )
    )
