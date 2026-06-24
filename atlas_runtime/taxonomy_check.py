"""Post-generation taxonomy check with frozen snapshots and adaptive batches."""

from __future__ import annotations

import hashlib
import json
import os
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
DEFAULT_MIN_ACTIVE_CODES = 2
DEFAULT_JUDGE_MAX_RETRIES = 1
JudgeCall = Callable[[str, str], str]


@dataclass(frozen=True)
class TraceUnit:
    problem_id: str
    unit_id: str
    text: str
    chunk_index: int
    chunk_total: int
    outcome: dict[str, Any] | None = None


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
    outcomes = _load_outcomes(workspace)
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

    units = _make_units(records, usable, outcomes)
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


def _make_units(
    records: list[dict[str, Any]],
    usable_tokens: int,
    outcomes: dict[str, dict[str, Any]] | None = None,
) -> list[TraceUnit]:
    outcomes = outcomes or {}
    # ATLAS_JUDGE_CHUNK_CHARS forces uniform chunk size for splitting the
    # trace into multiple judge units, regardless of the model's full input
    # budget. Useful with ATLAS_JUDGE_CAP=0 (full traces) to keep each judge
    # call focused on a smaller window — counters long-context attention
    # degradation. Unset (or 0) preserves the original behavior (split only
    # if the trace exceeds usable_tokens).
    env_chunk_chars = int(os.environ.get("ATLAS_JUDGE_CHUNK_CHARS", "0") or "0")
    split_budget = (
        max(1, env_chunk_chars // 4) if env_chunk_chars > 0 else usable_tokens
    )
    units: list[TraceUnit] = []
    for record in records:
        problem_id = str(record["problem_id"])
        outcome = outcomes.get(problem_id)
        text = format_support_trace(record)
        chunks = _split_text(text, split_budget)
        total = len(chunks)
        units.extend(
            TraceUnit(
                problem_id=problem_id,
                unit_id=f"{problem_id}:chunk-{index + 1}-of-{total}",
                text=chunk,
                chunk_index=index + 1,
                chunk_total=total,
                outcome=outcome,
            )
            for index, chunk in enumerate(chunks)
        )
    return units


def _load_outcomes(workspace: ProgramWorkspace) -> dict[str, dict[str, Any]]:
    """Load optional per-trace outcome labels written by the runtime driver.

    The driver (e.g. run_officeqa_atlas.py) writes ``{session_id: {label,
    correct, gold, actual}}`` to ``.atlas-task-labels.json`` under the
    workspace root. When present, the judge uses it to focus on incorrect
    answers; when absent, the judge runs outcome-blind (original behavior).
    """
    path = workspace.root / ".atlas-task-labels.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    aliased: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        aliased[key] = value
        if key.startswith("claude-code:"):
            aliased[key.removeprefix("claude-code:")] = value
        else:
            aliased[f"claude-code:{key}"] = value
    return aliased


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
    blocks = []
    for unit in units:
        header = (
            f"### UNIT {unit.unit_id} (trace={unit.problem_id}, "
            f"chunk={unit.chunk_index}/{unit.chunk_total})"
        )
        outcome_line = ""
        if unit.outcome:
            label = unit.outcome.get("label", "?")
            gold = unit.outcome.get("gold", "")
            actual = unit.outcome.get("actual", "")
            correct = unit.outcome.get("correct")
            if correct is False:
                outcome_line = (
                    f"\n[OUTCOME] task={label} | gold={gold!r} | "
                    f"agent_answer={actual!r} | verdict=INCORRECT"
                )
            elif correct is True:
                outcome_line = (
                    f"\n[OUTCOME] task={label} | verdict=CORRECT"
                )
        blocks.append(f"{header}{outcome_line}\n{unit.text}")
    traces = "\n\n".join(blocks)
    return f"""Assign failure-mode codes to each trace unit based on the
evidence in that unit. A trace can earn any number of codes; the same
underlying failure can match more than one code when its evidence touches
multiple categories (for example, a wrong-column extraction is evidence
both for a data-source code and for a value-inconsistency code). A code
fires only with concrete evidence quoted verbatim from the same unit.
Never invent a code. When an OUTCOME line marks a trace INCORRECT, the
agent's final answer was wrong; the steps where that can occur include
data extraction, source selection, formula choice, arithmetic, rounding,
and output format.

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
        if quote and not _quote_in_unit(quote, unit.text):
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


def _quote_in_unit(quote: str, text: str) -> bool:
    """Match either decoded text or its representation inside JSONL.

    Claude Code traces are stored as raw JSONL, so a genuinely verbatim path
    such as a Windows user path appears with escaped backslashes. Keep quote
    validation strict while accepting that serialization boundary.
    """
    if quote in text:
        return True
    encoded = json.dumps(quote, ensure_ascii=False)[1:-1]
    return encoded in text


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
