"""Post-generation taxonomy check with frozen snapshots and adaptive batches."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .learning_calls import (
    format_support_trace,
    judge_json,
    parse_json_object,
    support_model_call,
)
from .models import estimate_tokens, resolve_model_profile
from .program import ProgramWorkspace

DEFAULT_MAX_TRACES_PER_BATCH = 4
DEFAULT_MIN_ACTIVE_CODES = 5
DEFAULT_JUDGE_MAX_RETRIES = 1
JudgeCall = Callable[[str, str], str]


@dataclass(frozen=True)
class TraceUnit:
    problem_id: str
    unit_id: str
    text: str
    chunk_index: int
    chunk_total: int


@dataclass(frozen=True)
class TaxonomyCheckResult:
    accepted: bool
    candidate: dict[str, Any]
    snapshot_count: int
    active_codes: list[str]
    annotations: list[dict[str, Any]]
    failed_units: int
    reason: str


def check_taxonomy(
    workspace: ProgramWorkspace,
    candidate: dict[str, Any],
    *,
    atlas_model: str,
    judge_call: JudgeCall | None = None,
    max_traces_per_batch: int = DEFAULT_MAX_TRACES_PER_BATCH,
    min_active_codes: int = DEFAULT_MIN_ACTIVE_CODES,
    max_retries: int = DEFAULT_JUDGE_MAX_RETRIES,
) -> TaxonomyCheckResult:
    snapshot = freeze_trace_snapshot(workspace)
    files = [
        workspace.pending.root / entry["filename"]
        for entry in snapshot["traces"]
    ]
    records = []
    for path, entry in zip(files, snapshot["traces"]):
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            raise OSError(f"frozen trace changed during taxonomy check: {path}")
        records.append(json.loads(payload.decode("utf-8")))
    taxonomy_text = _taxonomy_text(candidate)
    prompt_overhead = estimate_tokens(_prompt(taxonomy_text, []))
    profile = resolve_model_profile(atlas_model)
    max_prompt_tokens = (
        int(profile.context_tokens * profile.safety_ratio)
        - profile.output_reserve_tokens
    )
    usable = max_prompt_tokens - prompt_overhead - 128
    if usable <= 0:
        raise ValueError("taxonomy/check prompt leaves no model input budget")

    units = _make_units(records, usable)
    batches = _pack_units(
        units,
        taxonomy_text,
        max_prompt_tokens,
        max_traces_per_batch,
    )
    call = judge_call or _default_judge_call
    annotations: list[dict[str, Any]] = []
    failed = 0
    valid_ids = {str(code["id"]) for code in candidate["codes"]}
    for batch in batches:
        parsed = _call_json(
            _prompt(taxonomy_text, batch),
            atlas_model,
            call,
            max_retries,
        )
        if parsed is None:
            failed += len(batch)
            continue
        by_unit = {
            str(item.get("unit_id")): item
            for item in parsed.get("per_unit", [])
            if isinstance(item, dict)
        }
        for unit in batch:
            item = by_unit.get(unit.unit_id)
            if item is None:
                failed += 1
                continue
            fired = _valid_firings(
                item.get("codes_fired", []),
                valid_ids,
                unit,
            )
            annotations.append(
                {
                    "problem_id": unit.problem_id,
                    "unit_id": unit.unit_id,
                    "codes_fired": fired,
                }
            )

    fired_by_trace: dict[str, set[str]] = {}
    evidence: dict[tuple[str, str], dict[str, Any]] = {}
    for annotation in annotations:
        trace_codes = fired_by_trace.setdefault(annotation["problem_id"], set())
        for firing in annotation["codes_fired"]:
            trace_codes.add(firing["code"])
            evidence.setdefault(
                (annotation["problem_id"], firing["code"]),
                firing,
            )
    support: dict[str, list[str]] = {code_id: [] for code_id in valid_ids}
    for problem_id, code_ids in fired_by_trace.items():
        for code_id in code_ids:
            support[code_id].append(problem_id)

    toned_codes = []
    active_codes = []
    for code in candidate["codes"]:
        code_id = str(code["id"])
        traces = sorted(set(support[code_id]))
        updated = dict(code)
        updated["support"] = len(traces)
        updated["support_tier"] = "ACTIVE" if traces else "PROVISIONAL"
        updated["firing_rounds"] = 1 if traces else 0
        updated["zero_strikes"] = 0 if traces else 1
        updated["gate_force"] = "advisory" if traces else "n/a"
        updated["support_traces"] = traces
        toned_codes.append(updated)
        if traces:
            active_codes.append(code_id)

    checked = {**candidate, "codes": toned_codes}
    accepted = len(active_codes) >= min_active_codes
    reason = (
        f"{len(active_codes)} ACTIVE code(s); need >= {min_active_codes}"
    )
    result = TaxonomyCheckResult(
        accepted=accepted,
        candidate=checked,
        snapshot_count=len(snapshot["traces"]),
        active_codes=sorted(active_codes),
        annotations=annotations,
        failed_units=failed,
        reason=reason,
    )
    _write_result(workspace, snapshot["check_id"], result)
    return result


def freeze_trace_snapshot(workspace: ProgramWorkspace) -> dict[str, Any]:
    """Capture immutable filenames+hashes without locking future appends."""
    entries = []
    for path in workspace.pending.trace_files():
        payload = path.read_bytes()
        entries.append(
            {
                "filename": path.name,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    snapshot = {
        "check_id": f"check-{uuid.uuid4().hex}",
        "traces": entries,
    }
    checks = workspace.root / "checks"
    checks.mkdir(exist_ok=True)
    target = checks / f"{snapshot['check_id']}.json"
    target.write_text(
        json.dumps(snapshot, indent=2) + "\n",
        encoding="utf-8",
    )
    return snapshot


def latest_snapshot_count(workspace: ProgramWorkspace) -> int:
    checks = workspace.root / "checks"
    files = sorted(checks.glob("check-*.json"), key=lambda path: path.stat().st_mtime)
    if not files:
        return workspace.pending.count()
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    return len(data.get("traces", []))


def _make_units(records: list[dict[str, Any]], usable_tokens: int) -> list[TraceUnit]:
    units: list[TraceUnit] = []
    for record in records:
        problem_id = str(record["problem_id"])
        text = format_support_trace(record)
        chunks = _split_text(text, usable_tokens)
        total = len(chunks)
        units.extend(
            TraceUnit(
                problem_id=problem_id,
                unit_id=f"{problem_id}:chunk-{index + 1}-of-{total}",
                text=chunk,
                chunk_index=index + 1,
                chunk_total=total,
            )
            for index, chunk in enumerate(chunks)
        )
    return units


def _split_text(text: str, max_tokens: int) -> list[str]:
    if estimate_tokens(text) <= max_tokens:
        return [text]
    chunks = []
    remaining = text
    max_chars = max(1, max_tokens * 3)
    while remaining:
        take = min(len(remaining), max_chars)
        piece = remaining[:take]
        while len(piece) > 1 and estimate_tokens(piece) > max_tokens:
            piece = piece[: max(1, int(len(piece) * 0.9))]
        chunks.append(piece)
        remaining = remaining[len(piece):]
    return chunks


def _pack_units(
    units: list[TraceUnit],
    taxonomy_text: str,
    max_prompt_tokens: int,
    max_units: int,
) -> list[list[TraceUnit]]:
    batches: list[list[TraceUnit]] = []
    current: list[TraceUnit] = []
    for unit in units:
        proposed = current + [unit]
        if current and (
            len(current) >= max_units
            or estimate_tokens(_prompt(taxonomy_text, proposed)) > max_prompt_tokens
        ):
            batches.append(current)
            current = []
        current.append(unit)
        if estimate_tokens(_prompt(taxonomy_text, current)) > max_prompt_tokens:
            raise ValueError(
                f"trace unit {unit.unit_id!r} exceeds the judge context budget"
            )
    if current:
        batches.append(current)
    return batches


def _write_result(
    workspace: ProgramWorkspace,
    check_id: str,
    result: TaxonomyCheckResult,
) -> None:
    target = workspace.root / "checks" / f"{check_id}.result.json"
    target.write_text(
        json.dumps(
            {
                "accepted": result.accepted,
                "snapshot_count": result.snapshot_count,
                "active_codes": result.active_codes,
                "failed_units": result.failed_units,
                "reason": result.reason,
                "annotations": result.annotations,
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )


def _taxonomy_text(candidate: dict[str, Any]) -> str:
    return "\n".join(
        f"{code['id']} | {code['name']} | {code['description']}"
        for code in candidate["codes"]
    )


def _prompt(taxonomy_text: str, units: Iterable[TraceUnit]) -> str:
    traces = "\n\n".join(
        f"### UNIT {unit.unit_id} (trace={unit.problem_id}, "
        f"chunk={unit.chunk_index}/{unit.chunk_total})\n{unit.text}"
        for unit in units
    )
    return f"""Assign failure-mode codes to each trace unit independently.
A code fires only with concrete evidence in that same unit. Be strict and
sparse. Never invent a code. If giving a quote, copy it verbatim from the unit.

TAXONOMY
{taxonomy_text}

TRACE UNITS
{traces}

Return only JSON:
{{"per_unit":[{{"unit_id":"...","codes_fired":[{{"code":"A.1","quote":"verbatim","evidence":"why"}}]}}]}}
"""


def _valid_firings(
    items: Any,
    valid_ids: set[str],
    unit: TraceUnit,
) -> list[dict[str, str]]:
    fired = []
    seen = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", ""))
        quote = str(item.get("quote", ""))
        if code not in valid_ids or code in seen:
            continue
        if quote and quote not in unit.text:
            continue
        seen.add(code)
        fired.append(
            {
                "code": code,
                "quote": quote,
                "evidence": str(item.get("evidence", ""))[:200],
                "chunk_index": unit.chunk_index,
            }
        )
    return fired


def _call_json(
    prompt: str,
    model: str,
    call: JudgeCall,
    max_retries: int,
) -> dict[str, Any] | None:
    return judge_json(
        prompt,
        model,
        call=call,
        max_retries=max_retries,
    )


def _parse_json_object(raw: Any) -> dict[str, Any] | None:
    return parse_json_object(raw)


def _default_judge_call(prompt: str, model: str) -> str:
    return support_model_call(prompt, model) or ""
