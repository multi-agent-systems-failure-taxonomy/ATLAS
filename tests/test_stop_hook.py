"""Smoke (A): Stop hook blocks unless the final-gate block is present;
3 failed repairs allow completion with an honest unresolved report."""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "claude_code_skill" / "hooks" / "stop.py"


def _run_hook(transcript_text: str, *, max_retries: int = 3) -> dict:
    """Write a fake JSONL transcript, invoke the Stop hook, return its
    decision JSON. The hook reads `transcript_path` from stdin event."""
    tmp = REPO / "tests" / "_tmp_transcript.jsonl"
    # Wrap each line so the hook's stream-json reader can extract text
    lines = []
    for chunk in transcript_text.split("\n"):
        if chunk.strip():
            lines.append(json.dumps({"type": "assistant",
                                     "content": [{"type": "text", "text": chunk}]}))
    tmp.write_text("\n".join(lines), encoding="utf-8")

    event = {"transcript_path": str(tmp)}
    env = {"PATH": sys.exec_prefix + ":" + sys.path[0],
           "ATLAS_MAX_FINAL_RETRIES": str(max_retries)}
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event).encode("utf-8"),
        capture_output=True,
        env={**__import__("os").environ, **env},
    )
    tmp.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return json.loads(proc.stdout)


def test_missing_gate_blocks():
    decision = _run_hook("I finished the task and submitted my patch. Done.")
    assert decision["decision"] == "block"
    assert "Final ATLAS status" in decision["reason"]
    assert decision["meta"]["gate_status"] == "MISSING"


def test_ready_to_submit_allows():
    transcript = (
        "I'm done. Running the final gate.\n"
        "Final ATLAS status: READY_TO_SUBMIT\n"
        "Codes checked: A.1, B.4\n"
        "Evidence: full test suite passes\n"
        "Repair attempts used: 0\n"
        "Final decision: submit\n"
    )
    decision = _run_hook(transcript)
    assert decision["decision"] == "approve"
    assert decision["meta"]["gate_status"] == "READY_TO_SUBMIT"
    assert decision["meta"]["repair_attempts_used"] == 0


def test_repair_required_with_attempts_left_blocks():
    transcript = (
        "Final ATLAS status: REPAIR_REQUIRED\n"
        "Codes checked: B.4\n"
        "Evidence: one failing test remains\n"
        "Repair attempts used: 1\n"
        "Final decision: repair\n"
    )
    decision = _run_hook(transcript, max_retries=3)
    assert decision["decision"] == "block"
    assert "REPAIR_REQUIRED" in decision["reason"]
    assert decision["meta"]["repair_attempts_used"] == 1


def test_repair_required_attempts_exhausted_allows_unresolved():
    transcript = (
        "Final ATLAS status: REPAIR_REQUIRED\n"
        "Codes checked: B.4\n"
        "Evidence: still one failing test after 3 repairs\n"
        "Repair attempts used: 3\n"
        "Final decision: report unresolved\n"
    )
    decision = _run_hook(transcript, max_retries=3)
    assert decision["decision"] == "approve"
    assert decision["meta"]["unresolved"] is True
    assert decision["meta"]["repair_attempts_used"] == 3


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
