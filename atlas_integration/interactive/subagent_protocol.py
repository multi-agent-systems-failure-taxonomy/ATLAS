"""Host-neutral claim and receipt protocol for in-task taxonomy subagents."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any

from atlas_integration.interactive.learning_jobs import (
    JOBS_DIR,
    LearningJobError,
    _job_lock,
    _read_json,
    _short_error,
    _write_json_atomic,
)
from atlas_runtime import ProgramWorkspace

DEFAULT_CLAIM_SECONDS = 1800
RECEIPT_OPEN = "<ATLAS_TAXONOMY_RECEIPT>"
RECEIPT_CLOSE = "</ATLAS_TAXONOMY_RECEIPT>"
MAX_RECEIPT_CHARS = 256_000
_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def claim_learning_job(
    workspace: ProgramWorkspace,
    *,
    conversation_id: str,
    lease_seconds: int = DEFAULT_CLAIM_SECONDS,
    host_label: str,
    subagent_capability: str,
    forbidden_cli: str,
) -> dict[str, Any] | None:
    """Claim the project's queued host job and return a ready-to-spawn task."""
    jobs_root = Path(workspace.root) / JOBS_DIR
    if not jobs_root.exists():
        return None
    manifest = workspace.load()
    active_job_id = (manifest.get("interactive_learning") or {}).get(
        "active_job_id"
    ) or (manifest.get("codex_learning") or {}).get("active_job_id")
    if not active_job_id:
        return None
    job_dir = jobs_root / str(active_job_id)
    job_path = job_dir / "job.json"
    if not job_path.exists():
        return None
    with _job_lock(job_dir):
        job = _read_json(job_path)
        if job.get("dispatch_mode") != "host_subagent":
            return None
        if job.get("state") == "claimed":
            expires_at = float(job.get("claim_expires_at_unix", 0) or 0)
            if not expires_at or time.time() < expires_at:
                return None
            _release_claim(job)
        if job.get("state") != "queued":
            return None
        now = time.time()
        token = secrets.token_urlsafe(24)
        job.update(
            state="claimed",
            claim_token=token,
            claimed_by=str(conversation_id),
            claimed_at_unix=now,
            claim_expires_at_unix=now + max(60, int(lease_seconds)),
            attempts=int(job.get("attempts", 0)) + 1,
            updated_at_unix=now,
        )
        _write_json_atomic(job_path, job)
    return _dispatch(
        job_dir,
        job,
        token,
        host_label=host_label,
        subagent_capability=subagent_capability,
        forbidden_cli=forbidden_cli,
    )


def complete_learning_job(
    job_dir: Path | str,
    *,
    claim_token: str,
    candidate: dict[str, Any],
) -> bool:
    """Submit a proposal receipt; the parent reconciler remains authoritative."""
    job_dir = Path(job_dir).expanduser().resolve()
    job_path = job_dir / "job.json"
    receipt_path = job_dir / "receipt.json"
    with _job_lock(job_dir):
        job = _read_json(job_path)
        if receipt_path.exists() and job.get("state") in {
            "awaiting_reconcile",
            "activating",
            "activated",
            "no_change",
        }:
            if not secrets.compare_digest(
                str(job.get("claim_token") or ""), str(claim_token)
            ):
                raise LearningJobError("learning job claim token mismatch")
            receipt = _read_json(receipt_path)
            return receipt.get("job_id") == job.get("job_id")
        _require_live_claim(job, claim_token)
        receipt = {
            "version": 1,
            "job_id": job["job_id"],
            "snapshot_hash": job["snapshot_hash"],
            "status": "candidate",
            "candidate": candidate,
            "completed_at_unix": time.time(),
        }
        _write_json_atomic(receipt_path, receipt)
        job["state"] = "awaiting_reconcile"
        job["updated_at_unix"] = time.time()
        job["last_error"] = None
        _write_json_atomic(job_path, job)
    return True


def fail_learning_job(
    job_dir: Path | str,
    *,
    claim_token: str,
    reason: str,
) -> bool:
    """Submit a failed receipt so normal reconciliation records the outcome."""
    job_dir = Path(job_dir).expanduser().resolve()
    job_path = job_dir / "job.json"
    with _job_lock(job_dir):
        job = _read_json(job_path)
        _require_live_claim(job, claim_token)
        _write_json_atomic(
            job_dir / "receipt.json",
            {
                "version": 1,
                "job_id": job["job_id"],
                "snapshot_hash": job["snapshot_hash"],
                "status": "failed",
                "error": _short_error(reason),
                "completed_at_unix": time.time(),
            },
        )
        job["state"] = "awaiting_reconcile"
        job["updated_at_unix"] = time.time()
        job["last_error"] = _short_error(reason)
        _write_json_atomic(job_path, job)
    return True


def capture_learning_receipt(
    workspace: ProgramWorkspace,
    event: dict[str, Any],
) -> str | None:
    """Capture one taxonomy receipt from a completed native subagent."""
    payload = _receipt_payload(event)
    if payload is None:
        return None
    job_id = str(payload.get("job_id") or "")
    if not _SAFE_JOB_ID.fullmatch(job_id):
        raise LearningJobError("taxonomy receipt has an invalid job id")
    job_dir = Path(workspace.root) / JOBS_DIR / job_id
    status = payload.get("status")
    if status == "candidate":
        complete_learning_job(
            job_dir,
            claim_token=str(payload.get("claim_token") or ""),
            candidate=payload.get("candidate"),
        )
    elif status == "failed":
        fail_learning_job(
            job_dir,
            claim_token=str(payload.get("claim_token") or ""),
            reason=str(payload.get("error") or "taxonomy subagent failed"),
        )
    else:
        raise LearningJobError("taxonomy receipt status must be candidate or failed")
    return job_id


def _dispatch(
    job_dir: Path,
    job: dict[str, Any],
    token: str,
    *,
    host_label: str,
    subagent_capability: str,
    forbidden_cli: str,
) -> dict[str, Any]:
    candidate_envelope = json.dumps(
        {
            "version": 1,
            "job_id": job["job_id"],
            "claim_token": token,
            "status": "candidate",
            "candidate": "<candidate JSON object>",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    failed_envelope = json.dumps(
        {
            "version": 1,
            "job_id": job["job_id"],
            "claim_token": token,
            "status": "failed",
            "error": "<concise reason>",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    task_prompt = (
        "You are the ATLAS taxonomy learning subagent for one frozen job. "
        "Work independently from the user's main task. Read only the UTF-8 prompt "
        f'at "{job_dir / "prompt.txt"}" and schema at '
        f'"{job_dir / "output.schema.json"}". Do not browse the repository, use '
        "network access, inspect credentials, edit files, or launch "
        f"{forbidden_cli}. "
        "Produce one candidate JSON object that satisfies the schema. Return only "
        "one compact receipt with no Markdown or surrounding text, replacing the "
        "candidate placeholder with that object:\n"
        f"{RECEIPT_OPEN}{candidate_envelope}{RECEIPT_CLOSE}\n"
        "If the job cannot be completed, return only this receipt with a concise "
        "error:\n"
        f"{RECEIPT_OPEN}{failed_envelope}{RECEIPT_CLOSE}"
    )
    directive = (
        f"ATLAS native taxonomy learning is ready. Launch one native {host_label} "
        "subagent "
        "now with the task prompt below, while continuing the user's main work in "
        f"parallel. Use {subagent_capability}, not {forbidden_cli}. "
        "Do not generate the taxonomy in the main agent and do not ask the user for "
        "an API key. Wait for the subagent before the final response when practical.\n\n"
        f"Job: {job['job_id']} ({job['kind']})\n"
        "SUBAGENT TASK BEGIN\n"
        f"{task_prompt}\n"
        "SUBAGENT TASK END"
    )
    return {
        "job_id": job["job_id"],
        "claim_token": token,
        "job_dir": str(job_dir),
        "task_name": f"atlas_{job['kind']}",
        "task_prompt": task_prompt,
        "directive": directive,
    }


def _receipt_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    candidates = []
    for key in (
        "last_assistant_message",
        "assistant_message",
        "message",
        "text",
    ):
        value = event.get(key)
        if isinstance(value, str):
            candidates.append(value)
    transcript = event.get("agent_transcript_path")
    if transcript:
        candidates.extend(_transcript_strings(Path(str(transcript))))
    for text in reversed(candidates):
        start = text.rfind(RECEIPT_OPEN)
        end = text.rfind(RECEIPT_CLOSE)
        if start < 0 or end <= start:
            continue
        raw = text[start + len(RECEIPT_OPEN) : end]
        if len(raw) > MAX_RECEIPT_CHARS:
            raise LearningJobError("taxonomy receipt exceeds the size limit")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _transcript_strings(path: Path) -> list[str]:
    try:
        with path.open("rb") as handle:
            size = path.stat().st_size
            handle.seek(max(0, size - 4_000_000))
            if size > 4_000_000:
                handle.readline()
            raw = handle.read().decode("utf-8", "replace")
    except OSError:
        return []
    strings: list[str] = []
    for line in raw.splitlines()[-128:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        strings.extend(_assistant_strings(item))
    return strings


def _assistant_strings(item: Any) -> list[str]:
    if not isinstance(item, dict):
        return []
    payload = item.get("payload")
    if item.get("type") == "event_msg" and isinstance(payload, dict):
        if payload.get("type") == "agent_message":
            return _nested_strings(payload.get("message"))
        return []
    if item.get("type") == "response_item" and isinstance(payload, dict):
        if payload.get("type") == "message" and payload.get("role") == "assistant":
            return _nested_strings(payload.get("content"))
        return []
    if item.get("role") == "assistant":
        return _nested_strings(item)
    if item.get("type") == "assistant":
        return _nested_strings(item.get("message") or item)
    return []


def _nested_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _nested_strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _nested_strings(item)]
    return []


def _require_live_claim(job: dict[str, Any], token: str) -> None:
    if job.get("dispatch_mode") != "host_subagent":
        raise LearningJobError("job is not assigned to a host-subagent path")
    if job.get("state") != "claimed":
        raise LearningJobError("learning job is not currently claimed")
    if not secrets.compare_digest(str(job.get("claim_token") or ""), str(token)):
        raise LearningJobError("learning job claim token mismatch")
    expires_at = float(job.get("claim_expires_at_unix", 0) or 0)
    if not expires_at or time.time() >= expires_at:
        raise LearningJobError("learning job claim has expired")


def _release_claim(job: dict[str, Any]) -> None:
    job["state"] = "queued"
    for key in (
        "claim_token",
        "claimed_by",
        "claimed_at_unix",
        "claim_expires_at_unix",
    ):
        job.pop(key, None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ATLAS subagent receipt protocol")
    subparsers = parser.add_subparsers(dest="command", required=True)
    complete = subparsers.add_parser("complete")
    complete.add_argument("--job-dir", required=True)
    complete.add_argument("--claim-token", required=True)
    complete.add_argument("--candidate", required=True)
    failed = subparsers.add_parser("fail")
    failed.add_argument("--job-dir", required=True)
    failed.add_argument("--claim-token", required=True)
    failed.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "complete":
            candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
            complete_learning_job(
                args.job_dir,
                claim_token=args.claim_token,
                candidate=candidate,
            )
        else:
            fail_learning_job(
                args.job_dir,
                claim_token=args.claim_token,
                reason=args.reason,
            )
    except (OSError, ValueError, json.JSONDecodeError, LearningJobError) as exc:
        print(f"ATLAS taxonomy receipt failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "command": args.command}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
