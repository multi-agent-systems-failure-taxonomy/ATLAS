#!/usr/bin/env python3
"""Stop hook — blocking. Denies completion until the agent emits the
final-gate block. Read by Claude Code via stdin (JSON event), writes a
decision JSON to stdout.

Hook contract (Claude Code Stop hook):
  - stdin:  JSON with at least `transcript_path` (path to the session transcript)
  - stdout: JSON {"decision": "block", "reason": "..."} to block completion,
            or empty / {"decision": "approve"} to allow.
  - exit code 0 in both cases; the decision JSON is what controls behavior.

Behavior:
  - READY_TO_SUBMIT in the last gate block       -> allow + push Trace to accumulator
  - REPAIR_REQUIRED with attempts < max          -> BLOCK, ask agent to repair
  - REPAIR_REQUIRED with attempts >= max         -> allow + push Trace, mark unresolved
  - No final-gate block in the transcript        -> BLOCK, ask agent to emit it

Evidence-gated: defaults to allow, only blocks on concrete evidence of an
unresolved issue (or a missing gate block on a non-trivial session). Must NOT
nag repair on a clean finish.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

GATE_PATTERN = re.compile(
    r"Final\s+ATLAS\s+status\s*:\s*(READY_TO_SUBMIT|REPAIR_REQUIRED)",
    re.IGNORECASE,
)
REPAIR_PATTERN = re.compile(
    r"Repair\s+attempts\s+used\s*:\s*(\d+)",
    re.IGNORECASE,
)
EVIDENCE_PATTERN = re.compile(
    r"Evidence\s*:\s*([^\n]+)",
    re.IGNORECASE,
)
CODES_PATTERN = re.compile(
    r"Codes\s+checked\s*:\s*([^\n]+)",
    re.IGNORECASE,
)

MAX_RETRIES = int(os.environ.get("ATLAS_MAX_FINAL_RETRIES", "3"))


def _read_transcript(transcript_path: Path) -> str:
    """Stream-json transcript -> concatenated text content for gate scanning."""
    if not transcript_path.exists():
        return ""
    out: list[str] = []
    for line in transcript_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
            continue
        for msg in _iter_text_chunks(obj):
            out.append(msg)
    return "\n".join(out)


def _iter_text_chunks(obj):
    if isinstance(obj, dict):
        content = obj.get("content")
        if isinstance(content, str):
            yield content
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("text"):
                        yield item["text"]
                    if item.get("thinking"):
                        yield item["thinking"]
                    if item.get("input"):
                        try:
                            yield json.dumps(item["input"])
                        except Exception:
                            pass
        for key in ("message", "result", "text", "thinking"):
            val = obj.get(key)
            if isinstance(val, str):
                yield val
            elif isinstance(val, dict):
                yield from _iter_text_chunks(val)


def _classify(transcript_text: str, *, max_retries: int) -> tuple[str, str, dict]:
    """Return (decision, reason, meta) where decision in {"allow", "block_repair",
    "block_missing", "allow_unresolved"}."""
    gates = list(GATE_PATTERN.finditer(transcript_text))
    if not gates:
        return ("block_missing",
                "No 'Final ATLAS status:' block found. Emit the final-gate block "
                "(all five fields) before completing this task.",
                {"gate_status": "MISSING"})

    last = gates[-1].group(1).upper()
    reps = list(REPAIR_PATTERN.finditer(transcript_text))
    repair_attempts = int(reps[-1].group(1)) if reps else 0

    if last == "READY_TO_SUBMIT":
        return ("allow",
                f"final gate READY_TO_SUBMIT (after {repair_attempts} repair attempts)",
                {"gate_status": "READY_TO_SUBMIT",
                 "repair_attempts_used": repair_attempts})

    # REPAIR_REQUIRED
    if repair_attempts >= max_retries:
        return ("allow_unresolved",
                f"REPAIR_REQUIRED with {repair_attempts}/{max_retries} attempts used "
                f"— allowing completion with unresolved report",
                {"gate_status": "REPAIR_REQUIRED",
                 "repair_attempts_used": repair_attempts,
                 "unresolved": True})

    return ("block_repair",
            f"REPAIR_REQUIRED ({repair_attempts}/{max_retries} attempts used). "
            f"Perform one focused repair targeting the highest-impact unresolved "
            f"issue, run the relevant verification, re-emit the final-gate block.",
            {"gate_status": "REPAIR_REQUIRED",
             "repair_attempts_used": repair_attempts})


def _push_trace(transcript_path: Path, transcript_text: str, meta: dict) -> bool:
    """Push a Trace into the in-process accumulator if importable.

    Importable when the host script that ran the conversation has imported
    claude_code_skill.accumulator. If the hook fires as a stand-alone process
    with no parent host, this is a no-op — that case is the durable-store
    territory (OUT OF SCOPE for simple scenario)."""
    try:
        from claude_code_skill.accumulator import Trace, get_accumulator
    except ImportError:
        return False
    ev_m = EVIDENCE_PATTERN.search(transcript_text)
    codes_m = CODES_PATTERN.search(transcript_text)
    trace = Trace(
        task_id=str(transcript_path.stem),
        transcript=[],   # full transcript intentionally NOT carried into accumulator
        tool_calls=[],
        final_gate_status=meta.get("gate_status", "MISSING"),
        repair_attempts_used=int(meta.get("repair_attempts_used", 0)),
        evidence=ev_m.group(1).strip() if ev_m else "",
        outcome=("unresolved_reported" if meta.get("unresolved") else "submitted"),
        metadata={
            "codes_checked": codes_m.group(1).strip() if codes_m else "",
            "source": "stop_hook",
        },
    )
    get_accumulator().add_trace(trace)
    return True


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        event = {}

    transcript_path = Path(event.get("transcript_path", ""))
    text = _read_transcript(transcript_path) if transcript_path else ""
    decision, reason, meta = _classify(text, max_retries=MAX_RETRIES)

    if decision in ("allow", "allow_unresolved"):
        _push_trace(transcript_path, text, meta)
        out = {"decision": "approve", "reason": reason, "meta": meta}
    else:
        out = {"decision": "block", "reason": reason, "meta": meta}

    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
