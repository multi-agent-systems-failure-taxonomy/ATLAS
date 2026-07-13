"""Proposal-only Claude Code worker for ATLAS taxonomy learning jobs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from atlas_integration.interactive.learning_jobs import (
    LearningJobError,
    _job_lock,
    _read_json,
    _short_error,
    _write_json_atomic,
)
from atlas_integration.interactive.worker_contract import build_prompt, candidate_schema


def build_claude_command(job: dict[str, Any]) -> list[str]:
    cli = job.get("worker_cli_path") or job.get("claude_cli_path")
    if not cli:
        raise LearningJobError("Claude worker job has no CLI path")
    command = [
        str(cli),
        "--safe-mode",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(candidate_schema(), separators=(",", ":")),
    ]
    model = job.get("worker_model")
    if isinstance(model, str) and model.strip():
        command.extend(["--model", model.strip()])
    command.append("-p")
    return command


def run_worker(job_dir: Path | str, *, runner=None) -> int:
    """Claim an immutable job, call Claude Code, and journal its proposal."""
    job_dir = Path(job_dir).expanduser().resolve()
    job_path = job_dir / "job.json"
    with _job_lock(job_dir):
        job = _read_json(job_path)
        if job.get("state") != "queued":
            return 0
        job["state"] = "running"
        job["attempts"] = int(job.get("attempts", 0)) + 1
        job["worker_pid"] = os.getpid()
        job["started_at_unix"] = time.time()
        job["updated_at_unix"] = time.time()
        _write_json_atomic(job_path, job)

    snapshot = _read_json(job_dir / "snapshot.json")
    prompt = build_prompt(snapshot)
    command = build_claude_command(job)
    run = runner or _run_claude
    try:
        completed = run(
            command,
            prompt=prompt,
            job_dir=job_dir,
            timeout_seconds=int(job.get("worker_timeout_seconds", 1800)),
        )
        stdout = str(getattr(completed, "stdout", "") or "")
        stderr = str(getattr(completed, "stderr", "") or "")
        (job_dir / "events.jsonl").write_text(stdout, encoding="utf-8")
        (job_dir / "stderr.log").write_text(stderr, encoding="utf-8")
        returncode = int(getattr(completed, "returncode", completed))
        if returncode != 0:
            raise LearningJobError(f"Claude worker exited with code {returncode}")
        envelope = json.loads(stdout)
        if envelope.get("is_error"):
            raise LearningJobError(str(envelope.get("result") or "Claude worker failed"))
        candidate = envelope.get("structured_output")
        if candidate is None and isinstance(envelope.get("result"), str):
            candidate = json.loads(envelope["result"])
        if not isinstance(candidate, dict):
            raise LearningJobError("Claude worker returned no structured candidate")
        _write_json_atomic(job_dir / "candidate.json", candidate)
        receipt = {
            "version": 1,
            "job_id": job["job_id"],
            "snapshot_hash": job["snapshot_hash"],
            "status": "candidate",
            "candidate": candidate,
            "completed_at_unix": time.time(),
        }
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 - the receipt records worker failure
        receipt = {
            "version": 1,
            "job_id": job["job_id"],
            "snapshot_hash": job["snapshot_hash"],
            "status": "failed",
            "error": _short_error(str(exc)),
            "completed_at_unix": time.time(),
        }
        exit_code = 1

    _write_json_atomic(job_dir / "receipt.json", receipt)
    with _job_lock(job_dir):
        latest = _read_json(job_path)
        if latest.get("state") == "running":
            latest["state"] = "awaiting_reconcile"
            latest["updated_at_unix"] = time.time()
            latest["last_error"] = receipt.get("error")
            _write_json_atomic(job_path, latest)
    return exit_code


def _run_claude(
    command: list[str],
    *,
    prompt: str,
    job_dir: Path,
    timeout_seconds: int,
):
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    return subprocess.run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        cwd=job_dir,
        timeout=timeout_seconds,
        check=False,
        creationflags=creationflags,
        env=env,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one ATLAS Claude learning job.")
    parser.add_argument("--job-dir", required=True)
    args = parser.parse_args(argv)
    return run_worker(args.job_dir)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
