#!/usr/bin/env python3
"""PostToolUse hook — throttled checkpoint reminder.

Fires only on OBSERVABLE failures (test failure / non-zero exit / error trace).
Skips successful calls entirely. Three throttles:

  1. Frequency:   at most once every N tool calls (default 5).
  2. Debounce:    suppress identical-error repeats.
  3. Recency:     suppress if a checkpoint reminder already fired in the last
                  K turns (default 3).

State is kept in a per-session JSON file under /tmp/. Per-session because the
hook fires in fresh subprocesses; we need to remember when the last reminder
was emitted.

Output is a lightweight stderr message — NOT a heavy mandatory block. Claude
Code surfaces stderr to the agent as a system note.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

FAILURE_PATTERNS = [
    re.compile(r"\bTraceback \(most recent call last\)"),
    re.compile(r"\bAssertionError\b"),
    re.compile(r"\bFAILED\b"),
    re.compile(r"\berror:\s", re.IGNORECASE),
    re.compile(r"\bnon-zero exit\b", re.IGNORECASE),
    re.compile(r"\bExit\s+code\s*[:=]\s*[1-9]\d*", re.IGNORECASE),
    re.compile(r"\bModuleNotFoundError\b"),
    re.compile(r"\bImportError\b"),
    re.compile(r"\bSyntaxError\b"),
    re.compile(r"\bFAIL\b\s*[:=]"),
]

THROTTLE_EVERY_N_CALLS = int(os.environ.get("ATLAS_POSTTOOL_THROTTLE", "5"))
RECENCY_WINDOW_TURNS = int(os.environ.get("ATLAS_POSTTOOL_RECENCY", "3"))

CHECKPOINT_REMINDER = (
    "[ATLAS checkpoint reminder] A tool call just returned a failure signature "
    "(test failure / error / non-zero exit). Consider running the major-segment "
    "checkpoint before continuing — 4 lines, plain text: Checkpoint, Relevant "
    "codes, Evidence, Next action."
)


def _state_path(session_id: str) -> Path:
    base = Path(tempfile.gettempdir()) / "atlas_skill_hooks"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"posttool_{session_id}.json"


def _load_state(session_id: str) -> dict:
    p = _state_path(session_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"call_index": 0, "last_fired_call_index": -10**9,
            "last_error_hash": "", "last_checkpoint_call_index": -10**9}


def _save_state(session_id: str, state: dict) -> None:
    _state_path(session_id).write_text(json.dumps(state), encoding="utf-8")


def _is_failure(output: str) -> bool:
    return any(p.search(output) for p in FAILURE_PATTERNS)


def _err_hash(output: str) -> str:
    return hashlib.sha1(output.encode("utf-8", "replace")[:4000]).hexdigest()[:10]


def _checkpoint_seen_recently(transcript_text: str, *, within: int) -> bool:
    # Look for the last N "Checkpoint:" markers
    markers = [m.start() for m in re.finditer(r"Checkpoint\s*:", transcript_text, re.IGNORECASE)]
    if not markers:
        return False
    # If the most recent marker is within `within` lines of the end, consider recent
    tail = transcript_text[-3000:]
    return bool(re.search(r"Checkpoint\s*:", tail, re.IGNORECASE))


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    session_id = str(event.get("session_id") or event.get("conversation_id") or "default")
    tool_output = (event.get("tool_result") or event.get("output") or "")
    if isinstance(tool_output, dict):
        tool_output = json.dumps(tool_output)
    tool_output = str(tool_output)

    state = _load_state(session_id)
    state["call_index"] += 1
    call_i = state["call_index"]

    # Skip non-failures
    if not _is_failure(tool_output):
        _save_state(session_id, state)
        return 0

    # Throttle: at most once every N calls
    if call_i - state["last_fired_call_index"] < THROTTLE_EVERY_N_CALLS:
        _save_state(session_id, state)
        return 0

    # Debounce: skip identical-error repeats
    h = _err_hash(tool_output)
    if h == state["last_error_hash"]:
        _save_state(session_id, state)
        return 0

    # Recency: if a checkpoint was emitted in the last RECENCY_WINDOW_TURNS
    transcript_path = event.get("transcript_path")
    if transcript_path and Path(transcript_path).exists():
        text = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
        if _checkpoint_seen_recently(text, within=RECENCY_WINDOW_TURNS):
            _save_state(session_id, state)
            return 0

    # Fire the reminder
    state["last_fired_call_index"] = call_i
    state["last_error_hash"] = h
    _save_state(session_id, state)

    print(CHECKPOINT_REMINDER, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
