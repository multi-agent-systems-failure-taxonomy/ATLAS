"""Durable, project-scoped learning jobs for interactive integrations.

The child harness process is deliberately proposal-only: it reads an immutable
snapshot and writes a receipt. Normal hook execution validates and activates
that receipt while the project has no active episode.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from finding import store

from atlas_runtime.learning_calls import outcome_blind_trace
from atlas_runtime.program import ProgramWorkspace
from atlas_runtime.refinement import structural_diff
from atlas_runtime.traces import GenerationTrace, TraceStore

JOB_PROTOCOL_VERSION = 1
PROMPT_VERSION = 1
JOBS_DIR = "learning_jobs"
TERMINAL_STATES = {"activated", "no_change", "failed", "rejected"}


class LearningJobError(RuntimeError):
    """Raised when a native learning job cannot be safely queued or applied."""


def enqueue_learning_job(
    workspace: ProgramWorkspace,
    *,
    kind: str,
    store_dir: Path | str,
    trace_root: Path | str,
    task_group: str,
    conversation_id: str,
    worker_model: str | None = None,
    codex_cli_path: Path | str | None = None,
    worker_cli_path: Path | str | None = None,
    worker_timeout_seconds: int = 1800,
    worker_driver: str = "codex_subagent",
    worker_label: str = "Codex taxonomy subagent",
    worker_module: str = "atlas_integration.codex.native_worker",
    job_prefix: str = "codex",
    launcher: Callable[[Path], None] | None = None,
) -> str:
    """Freeze one evidence snapshot and launch at most one worker for it."""
    if kind not in {"generation", "refinement"}:
        raise ValueError("learning job kind must be generation or refinement")
    learning = workspace.load().get("codex_learning") or {}
    active_job_id = learning.get("active_job_id")
    if active_job_id:
        active_path = workspace.root / JOBS_DIR / str(active_job_id) / "job.json"
        if active_path.exists():
            active_job = _read_json(active_path)
            if (
                active_job.get("kind") == kind
                and active_job.get("state") not in TERMINAL_STATES
            ):
                return str(active_job_id)
    snapshot = _build_snapshot(
        workspace,
        kind=kind,
        store_dir=Path(store_dir),
        trace_root=Path(trace_root),
        task_group=task_group,
    )
    snapshot_hash = _hash_payload(snapshot)
    job_id = f"{job_prefix}-{kind}-{snapshot_hash[:16]}"
    job_dir = workspace.root / JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    snapshot_record = {**snapshot, "snapshot_hash": snapshot_hash}
    snapshot_path = job_dir / "snapshot.json"
    if snapshot_path.exists():
        existing = _read_json(snapshot_path)
        if existing != snapshot_record:
            raise LearningJobError(f"snapshot collision for {job_id}")
    else:
        _write_json_atomic(snapshot_path, snapshot_record)

    resolved_cli = None
    requested_cli = worker_cli_path if worker_cli_path is not None else codex_cli_path
    if launcher is None or requested_cli is not None:
        if worker_driver == "codex_subagent":
            resolved_cli = resolve_codex_cli(requested_cli)
        elif requested_cli is not None:
            resolved_cli = Path(requested_cli).expanduser().resolve()
            if not resolved_cli.is_file():
                raise LearningJobError(f"worker CLI was not found: {resolved_cli}")
        else:
            raise LearningJobError(
                f"{worker_driver} requires an explicit worker_cli_path"
            )
    job_path = job_dir / "job.json"
    with _job_lock(job_dir):
        if job_path.exists():
            job = _read_json(job_path)
            if job.get("snapshot_hash") != snapshot_hash:
                raise LearningJobError(f"job identity collision for {job_id}")
            if job.get("state") not in TERMINAL_STATES:
                return job_id
            if job.get("state") in {"activated", "no_change", "rejected"}:
                return job_id
            attempt = int(job.get("attempts", 0)) + 1
        else:
            attempt = 1
        for name in ("candidate.json", "receipt.json", "events.jsonl", "stderr.log"):
            (job_dir / name).unlink(missing_ok=True)
        now = time.time()
        job = {
            "version": JOB_PROTOCOL_VERSION,
            "job_id": job_id,
            "kind": kind,
            "state": "queued",
            "snapshot_hash": snapshot_hash,
            "parent_taxonomy_id": snapshot.get("parent_taxonomy_id"),
            "program_id": snapshot["program_id"],
            "repo": snapshot["repo"],
            "task_group": task_group,
            "conversation_id": conversation_id,
            "trace_count": len(snapshot["traces"]),
            "attempts": attempt - 1,
            "worker_model": worker_model,
            "worker_driver": worker_driver,
            "worker_label": worker_label,
            "worker_module": worker_module,
            "worker_cli_path": str(resolved_cli) if resolved_cli else None,
            "codex_cli_path": str(resolved_cli) if resolved_cli else None,
            "worker_timeout_seconds": int(worker_timeout_seconds),
            "created_at_unix": float(job.get("created_at_unix", now))
            if job_path.exists()
            else now,
            "updated_at_unix": now,
            "last_error": None,
        }
        _write_json_atomic(job_path, job)

    with workspace.locked_manifest() as manifest:
        learning = manifest.setdefault("codex_learning", _new_learning_state())
        active = learning.get("active_job_id")
        if active and active != job_id:
            active_path = workspace.root / JOBS_DIR / str(active) / "job.json"
            active_job = _read_json(active_path) if active_path.exists() else {}
            if active_job.get("state") not in TERMINAL_STATES:
                raise LearningJobError(
                    f"project already has active native learning job {active}"
                )
        learning["active_job_id"] = job_id
        learning.setdefault("jobs", {})[job_id] = _job_summary(job)

    try:
        if launcher is not None:
            launcher(job_dir)
        else:
            _spawn_worker(job_dir, worker_module=worker_module)
    except Exception as exc:
        with _job_lock(job_dir):
            job = _read_json(job_path)
            job.update(
                state="failed",
                last_error=f"could not launch {worker_label}: {exc}",
                updated_at_unix=time.time(),
            )
            _write_json_atomic(job_path, job)
        _clear_active_job(workspace, job_id)
        raise

    rendered_worker_label = worker_label
    if worker_model:
        rendered_worker_label += f" ({worker_model})"
    else:
        rendered_worker_label += " (session default model)"
    _append_notice(
        workspace,
        notice_id=f"trigger:{job_id}:attempt:{attempt}",
        conversation_id=conversation_id,
        text=(
            f"ATLAS taxonomy {kind} triggered\n"
            f"Project/group: {snapshot['repo']} / {task_group}\n"
            f"Evidence: {len(snapshot['traces'])} completed episode traces\n"
            f"Worker: {rendered_worker_label}\n"
            "Current taxonomy remains active while learning continues."
        ),
    )
    return job_id


def reconcile_learning_jobs(
    workspace: ProgramWorkspace,
    *,
    store_dir: Path | str,
    trace_root: Path | str,
) -> None:
    """Validate completed receipts and resume any interrupted activation."""
    jobs_root = workspace.root / JOBS_DIR
    if not jobs_root.exists():
        return
    for job_dir in sorted(path for path in jobs_root.iterdir() if path.is_dir()):
        try:
            _reconcile_one(
                workspace,
                job_dir,
                store_dir=Path(store_dir),
                trace_root=Path(trace_root),
            )
        except (OSError, ValueError, LearningJobError):
            # A journaled activation is retried on the next hook event. Do not
            # make ordinary Codex work fail because reconciliation is pending.
            continue


def drain_learning_notices(
    workspace: ProgramWorkspace,
    conversation_id: str,
) -> list[str]:
    """Consume notices addressed to one conversation exactly once."""
    consumed: list[str] = []
    with workspace.locked_manifest() as manifest:
        learning = manifest.setdefault("codex_learning", _new_learning_state())
        remaining = []
        for notice in learning.setdefault("notices", []):
            if notice.get("conversation_id") == conversation_id:
                text = notice.get("text")
                if isinstance(text, str) and text.strip():
                    consumed.append(text)
            else:
                remaining.append(notice)
        learning["notices"] = remaining[-100:]
    return consumed


def resolve_codex_cli(explicit: Path | str | None = None) -> Path:
    """Locate the authenticated Codex CLI without reading its credential files."""
    candidates = [
        str(explicit) if explicit else None,
        os.environ.get("CODEX_CLI_PATH"),
        shutil.which("codex"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser().resolve()
        if path.is_file():
            return path
    raise LearningJobError(
        "Codex CLI was not found; set codex.codex_cli_path or run from Codex"
    )


def _build_snapshot(
    workspace: ProgramWorkspace,
    *,
    kind: str,
    store_dir: Path,
    trace_root: Path,
    task_group: str,
) -> dict[str, Any]:
    manifest = workspace.load()
    base: dict[str, Any] = {
        "version": JOB_PROTOCOL_VERSION,
        "prompt_version": PROMPT_VERSION,
        "kind": kind,
        "program_id": manifest["program_id"],
        "repo": str(manifest.get("repo") or ""),
        "task_group": task_group,
        "parent_taxonomy_id": None,
        "trace_names": [],
        "trace_refs": [],
        "traces": [],
        "current_taxonomy": None,
    }
    if kind == "generation":
        if manifest.get("taxonomy_id"):
            raise LearningJobError("generation is unnecessary after taxonomy activation")
        names: list[str] = []
        traces: list[dict[str, Any]] = []
        for path in workspace.pending.trace_files():
            try:
                trace = GenerationTrace.from_dict(_read_json(path))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            names.append(path.name)
            traces.append(outcome_blind_trace(trace.to_dict()))
        if not traces:
            raise LearningJobError("generation snapshot has no valid traces")
        base["trace_names"] = names
        base["traces"] = traces
        return base

    parent_id = manifest.get("taxonomy_id")
    if not parent_id:
        raise LearningJobError("refinement requires an active learned taxonomy")
    refs = list((manifest.get("refinement") or {}).get("trace_refs") or [])
    traces = []
    valid_refs = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        taxonomy_id = str(ref.get("taxonomy_id") or "")
        filename = str(ref.get("filename") or "")
        path = trace_root / taxonomy_id / filename
        try:
            trace = GenerationTrace.from_dict(_read_json(path))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        valid_refs.append({"taxonomy_id": taxonomy_id, "filename": filename})
        traces.append(outcome_blind_trace(trace.to_dict()))
    if not traces:
        raise LearningJobError("refinement snapshot has no valid traces")
    base["parent_taxonomy_id"] = str(parent_id)
    base["trace_refs"] = valid_refs
    base["traces"] = traces
    base["current_taxonomy"] = store.fetch_by_id(str(parent_id), store_dir)
    return base


def _reconcile_one(
    workspace: ProgramWorkspace,
    job_dir: Path,
    *,
    store_dir: Path,
    trace_root: Path,
) -> None:
    job_path = job_dir / "job.json"
    receipt_path = job_dir / "receipt.json"
    snapshot_path = job_dir / "snapshot.json"
    if not job_path.exists() or not snapshot_path.exists():
        return
    with _job_lock(job_dir):
        job = _read_json(job_path)
        if job.get("state") in TERMINAL_STATES:
            return
        if not receipt_path.exists() and job.get("state") in {
            "queued",
            "running",
            "awaiting_reconcile",
        }:
            timeout_seconds = max(1, int(job.get("worker_timeout_seconds", 1800)))
            updated_at = float(job.get("updated_at_unix", 0) or 0)
            if updated_at and time.time() - updated_at > timeout_seconds + 60:
                _fail_job(
                    workspace,
                    job_dir,
                    job,
                    (
                        "taxonomy worker produced no receipt before its "
                        f"{timeout_seconds}-second lease expired"
                    ),
                )
                return
        if not receipt_path.exists() and job.get("state") != "activating":
            return
        snapshot = _read_json(snapshot_path)
        if _hash_payload({k: v for k, v in snapshot.items() if k != "snapshot_hash"}) != snapshot.get("snapshot_hash"):
            _reject_job(workspace, job_dir, job, "immutable snapshot hash mismatch")
            return

        if job.get("state") != "activating":
            try:
                receipt = _read_json(receipt_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                _reject_job(
                    workspace,
                    job_dir,
                    job,
                    f"malformed worker receipt: {exc}",
                )
                return
            if receipt.get("job_id") != job.get("job_id"):
                _reject_job(workspace, job_dir, job, "receipt job id mismatch")
                return
            if receipt.get("snapshot_hash") != job.get("snapshot_hash"):
                _reject_job(workspace, job_dir, job, "receipt snapshot hash mismatch")
                return
            if receipt.get("status") == "failed":
                _fail_job(
                    workspace,
                    job_dir,
                    job,
                    str(receipt.get("error") or "taxonomy worker failed"),
                )
                return
            if receipt.get("status") != "candidate":
                _reject_job(workspace, job_dir, job, "unsupported receipt status")
                return
            try:
                candidate = validate_candidate(receipt.get("candidate"), snapshot)
            except LearningJobError as exc:
                _reject_job(workspace, job_dir, job, str(exc))
                return
            _write_json_atomic(job_dir / "validated_candidate.json", candidate)
            job["state"] = "activating"
            job["taxonomy_id"] = _taxonomy_id(job, candidate)
            job["updated_at_unix"] = time.time()
            _write_json_atomic(job_path, job)
        else:
            candidate = _read_json(job_dir / "validated_candidate.json")

        if workspace.load().get("active_sessions"):
            return
        try:
            if job["kind"] == "generation":
                activated = _activate_generation(
                    workspace,
                    job,
                    snapshot,
                    candidate,
                    store_dir=store_dir,
                    trace_root=trace_root,
                )
                outcome = "activated"
            else:
                activated, outcome = _activate_refinement(
                    workspace,
                    job,
                    snapshot,
                    candidate,
                    store_dir=store_dir,
                    trace_root=trace_root,
                )
        except LearningJobError as exc:
            _reject_job(workspace, job_dir, job, str(exc))
            return
        if not activated:
            return

        job["state"] = outcome
        job["updated_at_unix"] = time.time()
        job["last_error"] = None
        _write_json_atomic(job_path, job)
        _clear_active_job(workspace, job["job_id"], summary=_job_summary(job))
        if outcome == "no_change":
            result = f"Reviewed: {job['taxonomy_id']} remains active; no successor was needed"
        else:
            result = f"Activated: {job['taxonomy_id']}"
        _append_notice(
            workspace,
            notice_id=f"complete:{job['job_id']}",
            conversation_id=str(job["conversation_id"]),
            text=(
                f"ATLAS taxonomy {job['kind']} finished\n"
                f"Project/group: {job['repo']} / {job['task_group']}\n"
                f"{result}\n"
                f"Evidence: {job['trace_count']} frozen traces; "
                f"snapshot {str(job['snapshot_hash'])[:12]}; validation passed."
            ),
        )


def validate_candidate(candidate: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate structure and require every code to cite frozen evidence."""
    if not isinstance(candidate, dict):
        raise LearningJobError("candidate must be an object")
    decision = candidate.get("decision", "replace")
    if decision not in {"replace", "no_change"}:
        raise LearningJobError("candidate decision must be replace or no_change")
    if snapshot["kind"] == "generation" and decision != "replace":
        raise LearningJobError("generation cannot return no_change")
    domain = candidate.get("domain")
    summary = candidate.get("summary")
    codes = candidate.get("codes")
    if not isinstance(domain, str) or not domain.strip():
        raise LearningJobError("candidate domain must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise LearningJobError("candidate summary must be a non-empty string")
    if not isinstance(codes, list) or not codes:
        raise LearningJobError("candidate codes must be a non-empty list")
    trace_ids = {str(trace.get("problem_id")) for trace in snapshot["traces"]}
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    normalized_codes = []
    for index, code in enumerate(codes):
        if not isinstance(code, dict):
            raise LearningJobError(f"candidate code {index} must be an object")
        code_id = code.get("id")
        name = code.get("name")
        description = code.get("description")
        category = code.get("category")
        evidence = code.get("evidence")
        if not all(isinstance(value, str) and value.strip() for value in (code_id, name, description)):
            raise LearningJobError(f"candidate code {index} has incomplete fields")
        if category not in {"A", "B", "C"}:
            raise LearningJobError(f"candidate code {code_id} has invalid category")
        if code_id in seen_ids or name.casefold() in seen_names:
            raise LearningJobError(f"candidate code {code_id} is duplicated")
        if not isinstance(evidence, dict):
            raise LearningJobError(f"candidate code {code_id} has no evidence")
        cited = evidence.get("trace_ids")
        rationale = evidence.get("rationale")
        if not isinstance(cited, list) or not cited:
            raise LearningJobError(f"candidate code {code_id} cites no traces")
        if any(str(item) not in trace_ids for item in cited):
            raise LearningJobError(f"candidate code {code_id} cites foreign traces")
        if not isinstance(rationale, str) or not rationale.strip():
            raise LearningJobError(f"candidate code {code_id} has no evidence rationale")
        seen_ids.add(str(code_id))
        seen_names.add(str(name).casefold())
        normalized_codes.append(
            {
                "id": str(code_id).strip(),
                "name": str(name).strip(),
                "description": str(description).strip(),
                "category": category,
                "evidence": {
                    "trace_ids": [str(item) for item in cited],
                    "rationale": rationale.strip(),
                },
            }
        )
    return {
        "decision": decision,
        "repo": str(snapshot.get("repo") or ""),
        "domain": domain.strip(),
        "summary": summary.strip(),
        "codes": normalized_codes,
    }


def _activate_generation(
    workspace: ProgramWorkspace,
    job: dict[str, Any],
    snapshot: dict[str, Any],
    candidate: dict[str, Any],
    *,
    store_dir: Path,
    trace_root: Path,
) -> bool:
    taxonomy_id = str(job["taxonomy_id"])
    record = _taxonomy_record(taxonomy_id, candidate, job)
    destination = TraceStore(trace_root / taxonomy_id)
    destination.root.mkdir(parents=True, exist_ok=True)
    current_files = workspace.pending.trace_files()
    _copy_trace_files(current_files, destination.root)
    source_names = set(snapshot.get("trace_names") or [])
    later_names = [path.name for path in current_files if path.name not in source_names]
    with workspace.locked_manifest() as manifest:
        if manifest.get("active_sessions"):
            return False
        current = manifest.get("taxonomy_id")
        if current not in (None, taxonomy_id):
            raise LearningJobError(
                f"generation result is stale; project now uses {current}"
            )
        first_activation = current != taxonomy_id
        _ensure_taxonomy_record(record, store_dir)
        manifest["taxonomy_id"] = taxonomy_id
        manifest["generation"] = {"state": "complete", "last_error": None}
        if first_activation and later_names:
            refinement = manifest.setdefault("refinement", {})
            refs = refinement.setdefault("trace_refs", [])
            existing = {
                (str(item.get("taxonomy_id")), str(item.get("filename")))
                for item in refs
                if isinstance(item, dict)
            }
            for name in later_names:
                key = (taxonomy_id, name)
                if key not in existing:
                    refs.append({"taxonomy_id": taxonomy_id, "filename": name})
            refinement["traces_since_refinement"] = len(refs)
            refinement.setdefault("rounds_completed", 0)
            refinement.setdefault("state", "idle")
            refinement.setdefault("last_error", None)
    workspace.pending.integrate_into(destination)
    return True


def _activate_refinement(
    workspace: ProgramWorkspace,
    job: dict[str, Any],
    snapshot: dict[str, Any],
    candidate: dict[str, Any],
    *,
    store_dir: Path,
    trace_root: Path,
) -> tuple[bool, str]:
    parent_id = str(snapshot["parent_taxonomy_id"])
    taxonomy_id = str(job["taxonomy_id"])
    current_record = snapshot["current_taxonomy"]
    comparable_current = {
        "repo": current_record.get("repo", ""),
        "domain": current_record.get("domain", ""),
        "summary": current_record.get("summary", ""),
        "codes": current_record.get("codes", []),
    }
    comparable_candidate = {
        "repo": candidate["repo"],
        "domain": candidate["domain"],
        "summary": candidate["summary"],
        "codes": candidate["codes"],
    }
    no_change = candidate["decision"] == "no_change" or (
        _hash_payload(comparable_current) == _hash_payload(comparable_candidate)
    )
    current_id = workspace.load().get("taxonomy_id")
    if current_id not in (parent_id, taxonomy_id):
        raise LearningJobError(
            f"refinement result is stale; project now uses {current_id}"
        )
    if not no_change:
        record = _taxonomy_record(taxonomy_id, candidate, job)
    else:
        taxonomy_id = parent_id
        job["taxonomy_id"] = parent_id

    source_refs = {
        (str(item.get("taxonomy_id")), str(item.get("filename")))
        for item in snapshot.get("trace_refs") or []
        if isinstance(item, dict)
    }
    with workspace.locked_manifest() as manifest:
        if manifest.get("active_sessions"):
            return False, "no_change" if no_change else "activated"
        current_id = manifest.get("taxonomy_id")
        if current_id not in (parent_id, taxonomy_id):
            raise LearningJobError(
                f"refinement result is stale; project now uses {current_id}"
            )
        refinement = manifest.setdefault("refinement", {})
        first_activation = current_id == parent_id
        if not no_change:
            _ensure_taxonomy_record(record, store_dir)
            (trace_root / taxonomy_id).mkdir(parents=True, exist_ok=True)
            _write_json_atomic(
                job_dir_for(workspace, job["job_id"]) / "activation.json",
                {
                    "from_taxonomy_id": parent_id,
                    "to_taxonomy_id": taxonomy_id,
                    "diff": structural_diff(current_record, comparable_candidate),
                    "scope": "project_task_group",
                },
            )
        if first_activation:
            remaining = [
                item
                for item in refinement.get("trace_refs", [])
                if isinstance(item, dict)
                and (str(item.get("taxonomy_id")), str(item.get("filename")))
                not in source_refs
            ]
            refinement["trace_refs"] = remaining
            refinement["traces_since_refinement"] = len(remaining)
            refinement["rounds_completed"] = int(
                refinement.get("rounds_completed", 0)
            ) + 1
        manifest["taxonomy_id"] = taxonomy_id
        refinement["state"] = "complete"
        refinement["last_error"] = None
        refinement.pop("worker_kind", None)
        refinement.pop("worker_started_unix", None)
    return True, "no_change" if no_change else "activated"


def _taxonomy_record(
    taxonomy_id: str,
    candidate: dict[str, Any],
    job: dict[str, Any],
) -> dict[str, Any]:
    return {
        "taxonomy_id": taxonomy_id,
        "repo": candidate["repo"],
        "domain": candidate["domain"],
        "summary": candidate["summary"],
        "codes": candidate["codes"],
        "provenance": {
            "driver": str(job.get("worker_driver") or "codex_subagent"),
            "job_id": job["job_id"],
            "snapshot_hash": job["snapshot_hash"],
            "parent_taxonomy_id": job.get("parent_taxonomy_id"),
        },
    }


def _ensure_taxonomy_record(record: dict[str, Any], store_dir: Path) -> None:
    taxonomy_id = record["taxonomy_id"]
    if store.exists(taxonomy_id, store_dir):
        if store.fetch_by_id(taxonomy_id, store_dir) != record:
            raise LearningJobError(f"taxonomy id collision for {taxonomy_id}")
        return
    store.register(record, store_dir)


def _copy_trace_files(sources: list[Path], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for source in sources:
        payload = source.read_bytes()
        target = destination / source.name
        if target.exists():
            if target.read_bytes() != payload:
                raise LearningJobError(f"trace collision for {source.name}")
            continue
        temporary = destination / f".{source.name}.tmp"
        temporary.write_bytes(payload)
        os.replace(temporary, target)


def _taxonomy_id(job: dict[str, Any], candidate: dict[str, Any]) -> str:
    digest = _hash_payload(
        {
            "job_id": job["job_id"],
            "snapshot_hash": job["snapshot_hash"],
            "candidate": candidate,
        }
    )[:16]
    driver = str(job.get("worker_driver") or "codex_subagent")
    harness = driver.removesuffix("_subagent").replace("_", "-")
    return f"tax-{harness}-{digest}"


def _reject_job(
    workspace: ProgramWorkspace,
    job_dir: Path,
    job: dict[str, Any],
    reason: str,
) -> None:
    _finish_unsuccessful(workspace, job_dir, job, "rejected", reason)


def _fail_job(
    workspace: ProgramWorkspace,
    job_dir: Path,
    job: dict[str, Any],
    reason: str,
) -> None:
    _finish_unsuccessful(workspace, job_dir, job, "failed", reason)


def _finish_unsuccessful(
    workspace: ProgramWorkspace,
    job_dir: Path,
    job: dict[str, Any],
    state: str,
    reason: str,
) -> None:
    job.update(state=state, last_error=reason, updated_at_unix=time.time())
    _write_json_atomic(job_dir / "job.json", job)
    if job["kind"] == "generation":
        workspace.mark_generation("failed", reason)
        active_label = "MAST remains active"
    else:
        workspace.mark_refinement("failed", reason)
        active_label = "the current taxonomy remains active"
    _clear_active_job(workspace, job["job_id"], summary=_job_summary(job))
    _append_notice(
        workspace,
        notice_id=f"complete:{job['job_id']}:attempt:{job.get('attempts', 0)}",
        conversation_id=str(job["conversation_id"]),
        text=(
            f"ATLAS taxonomy {job['kind']} finished\n"
            f"Project/group: {job['repo']} / {job['task_group']}\n"
            f"Activated: none; {active_label}.\n"
            f"Evidence: snapshot {str(job['snapshot_hash'])[:12]}; "
            f"worker result was not applied: {_short_error(reason)}"
        ),
    )


def _append_notice(
    workspace: ProgramWorkspace,
    *,
    notice_id: str,
    conversation_id: str,
    text: str,
) -> None:
    with workspace.locked_manifest() as manifest:
        learning = manifest.setdefault("codex_learning", _new_learning_state())
        notices = learning.setdefault("notices", [])
        if any(item.get("id") == notice_id for item in notices):
            return
        notices.append(
            {
                "id": notice_id,
                "conversation_id": conversation_id,
                "text": text,
                "created_at_unix": time.time(),
            }
        )
        del notices[:-100]


def _clear_active_job(
    workspace: ProgramWorkspace,
    job_id: str,
    *,
    summary: dict[str, Any] | None = None,
) -> None:
    with workspace.locked_manifest() as manifest:
        learning = manifest.setdefault("codex_learning", _new_learning_state())
        if learning.get("active_job_id") == job_id:
            learning["active_job_id"] = None
        if summary is not None:
            learning.setdefault("jobs", {})[job_id] = summary
            jobs = learning["jobs"]
            if len(jobs) > 50:
                for old_id in list(jobs)[:-50]:
                    jobs.pop(old_id, None)


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: job.get(key)
        for key in (
            "job_id",
            "kind",
            "state",
            "snapshot_hash",
            "parent_taxonomy_id",
            "trace_count",
            "attempts",
            "taxonomy_id",
            "last_error",
            "updated_at_unix",
        )
    }


def _new_learning_state() -> dict[str, Any]:
    return {"active_job_id": None, "jobs": {}, "notices": []}


def _spawn_worker(job_dir: Path, *, worker_module: str) -> None:
    command = [
        sys.executable,
        "-m",
        worker_module,
        "--job-dir",
        str(job_dir),
    ]
    log_path = job_dir / "supervisor.log"
    log_fh = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_fh,
        "stderr": subprocess.STDOUT,
        "cwd": str(Path(__file__).resolve().parents[2]),
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
    process = subprocess.Popen(command, **kwargs)
    log_fh.close()
    if process.pid <= 0:
        raise LearningJobError("native worker did not return a process id")


def job_dir_for(workspace: ProgramWorkspace, job_id: str) -> Path:
    return workspace.root / JOBS_DIR / job_id


def _short_error(value: str, limit: int = 300) -> str:
    clean = " ".join(str(value).split())
    return clean if len(clean) <= limit else clean[: limit - 3] + "..."


def _hash_payload(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LearningJobError(f"{path.name} must contain an object")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


@contextmanager
def _job_lock(
    job_dir: Path,
    *,
    timeout: float = 5.0,
    stale_after: float = 3600.0,
) -> Iterator[None]:
    lock = job_dir / ".job.lock"
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale_after:
                    lock.rmdir()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for learning job lock {lock}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except FileNotFoundError:
            pass


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
