"""Initial MAST-to-generated-taxonomy learning transition.

Generation starts after N program warm-up traces (default 5). A generated
candidate has no taxonomy_id. Only an accepted candidate is assigned an id,
registered, given a trace folder, and activated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from finding import store

from .program import ProgramWorkspace
from .learning_calls import outcome_blind_trace
from .taxonomy_check import JudgeCall, check_taxonomy, latest_snapshot_count
from .traces import DEFAULT_TRACE_ROOT, GenerationTrace, TraceStore

DEFAULT_GENERATION_THRESHOLD = 5
Generator = Callable[[list[dict[str, Any]]], dict[str, Any]]
Approver = Callable[[dict[str, Any]], bool]


@dataclass(frozen=True)
class GenerationResult:
    action: str
    reason: str
    taxonomy_id: str | None = None


def _generation_output_dir(workspace: ProgramWorkspace) -> Path:
    """Vendored-pipeline scratch output, kept inside the program's own root.

    The pipeline owns one program per directory and generation is single-
    flighted, so a stable subdirectory is safe and cannot collide with another
    program (each program has a distinct root).
    """
    return workspace.root / "generation"


def _atlas_generate(
    traces: list[dict[str, Any]],
    atlas_model: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Call the vendored ATLAS pipeline at its public generation boundary.

    The vendored pipeline always writes ``taxonomy.json`` plus a timestamped
    copy to its output_dir (pipeline.py), regardless of ``save_intermediate``.
    Passing an explicit directory under the program's own root keeps those
    files inside the program's owned space and out of the worker's CWD —
    the vendored default (``resolve_output_dir(None)`` -> ``cwd/atlas_output``)
    is never reached.
    """
    from vendor.atlas import generate_taxonomy

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return generate_taxonomy(
        traces=[outcome_blind_trace(trace) for trace in traces],
        output_dir=output_dir,
        model=atlas_model,
        save_intermediate=True,
        verbose=False,
    )


def candidate_from_atlas(
    raw: dict[str, Any],
    *,
    repo: str = "",
) -> dict[str, Any]:
    """Convert ATLAS output into id-less codes for the flat taxonomy schema."""
    layer = raw.get("annotation_layer")
    if not isinstance(layer, dict):
        raise ValueError("ATLAS output has no annotation_layer object")
    codes: list[dict[str, Any]] = []
    for key, entries in layer.items():
        if not key.startswith("category_") or not isinstance(entries, list):
            continue
        # Canonical code `category` is the SHORT label (A/B/C), matching how
        # MAST uses short categories. The verbose A/B/C definitions stay in the
        # vendored output's category_definitions if ever needed.
        category = key.removeprefix("category_").upper()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            code_id = entry.get("code") or entry.get("id")
            name = entry.get("name")
            description = entry.get("definition") or entry.get("description")
            if not all(isinstance(value, str) and value for value in
                       (code_id, name, description)):
                continue
            code = {
                "id": code_id,
                "name": name,
                "description": description,
                "category": category,
            }
            for extra in ("severity", "applies_to_role"):
                if extra in entry:
                    code[extra] = entry[extra]
            codes.append(code)
    if not codes:
        raise ValueError("ATLAS output produced no usable failure modes")
    return {
        "repo": repo,
        "domain": _domain_name_from_atlas(raw),
        "codes": codes,
    }


def _domain_name_from_atlas(raw: dict[str, Any]) -> str:
    """Keep the display-only domain discovered by ATLAS pipeline Step 1."""
    full_layer = raw.get("full_layer")
    if not isinstance(full_layer, dict):
        return ""
    domain_info = full_layer.get("domain_info")
    if not isinstance(domain_info, dict):
        return ""
    domain = domain_info.get("domain")
    if not isinstance(domain, dict):
        return ""
    name = domain.get("name")
    return name.strip() if isinstance(name, str) else ""


def structurally_accept(candidate: dict[str, Any]) -> bool:
    """Temporary acceptance seam; quality judgment is intentionally future work."""
    return (
        isinstance(candidate, dict)
        and isinstance(candidate.get("repo"), str)
        and isinstance(candidate.get("domain"), str)
        and isinstance(candidate.get("codes"), list)
        and bool(candidate["codes"])
    )


def trigger_generation(
    workspace: ProgramWorkspace,
    *,
    store_dir: Path | str = store.DEFAULT_STORE_DIR,
    trace_root: Path | str = DEFAULT_TRACE_ROOT,
    threshold: int = DEFAULT_GENERATION_THRESHOLD,
    generation_stops: bool = False,
    generator: Generator | None = None,
    approver: Approver | None = None,
    atlas_model: str | None = None,
    taxonomy_check: bool = True,
    judge_call: JudgeCall | None = None,
    background_launcher: Callable[[], None] | None = None,
) -> GenerationResult:
    """Start generation when the MAST warm-up threshold is crossed."""
    count = workspace.pending.count()
    retry_after = workspace.generation_retry_after(threshold)
    if count < retry_after:
        return GenerationResult(
            "none",
            f"generation threshold not reached: {count}/{retry_after}",
        )
    if not workspace.try_begin_generation():
        return GenerationResult("none", "generation already running or unnecessary")

    if generation_stops:
        return run_generation_job(
            workspace,
            store_dir=store_dir,
            trace_root=trace_root,
            generator=generator,
            approver=approver,
            atlas_model=atlas_model,
            taxonomy_check=taxonomy_check,
            judge_call=judge_call,
            generation_threshold=threshold,
        )

    try:
        if background_launcher is not None:
            background_launcher()
        else:
            _spawn_worker(workspace.root, Path(store_dir), Path(trace_root))
    except Exception as exc:
        workspace.mark_generation("failed", str(exc))
        return GenerationResult("failed", f"could not start generation: {exc}")
    return GenerationResult(
        "started",
        "generation started in background; MAST remains active until approval",
    )


def run_generation_job(
    workspace: ProgramWorkspace,
    *,
    store_dir: Path | str = store.DEFAULT_STORE_DIR,
    trace_root: Path | str = DEFAULT_TRACE_ROOT,
    generator: Generator | None = None,
    approver: Approver | None = None,
    atlas_model: str | None = None,
    taxonomy_check: bool = True,
    judge_call: JudgeCall | None = None,
    generation_threshold: int = DEFAULT_GENERATION_THRESHOLD,
    activation_poll_seconds: float = 0.05,
    activation_timeout_seconds: float = 86_400,
) -> GenerationResult:
    """Generate, accept/reject, then transactionally register and activate."""
    model = atlas_model or workspace.load().get("atlas_model")
    if not model:
        workspace.mark_generation("failed", "atlas_model is required")
        return GenerationResult("failed", "atlas_model is required")
    try:
        while True:
            result = _generate_and_check_once(
                workspace,
                store_dir=Path(store_dir),
                trace_root=Path(trace_root),
                model=str(model),
                generator=generator,
                approver=approver,
                taxonomy_check=taxonomy_check,
                judge_call=judge_call,
                generation_threshold=generation_threshold,
                activation_poll_seconds=activation_poll_seconds,
                activation_timeout_seconds=activation_timeout_seconds,
            )
            if result.action != "retry_now":
                return result
    except Exception as exc:
        workspace.mark_generation("failed", str(exc))
        return GenerationResult(
            "failed",
            f"generation failed; MAST remains active and traces were preserved: {exc}",
        )
    finally:
        try:
            from .dashboard import stop_dashboard_if_idle

            stop_dashboard_if_idle(workspace)
        except Exception:
            pass


def _generate_and_check_once(
    workspace: ProgramWorkspace,
    *,
    store_dir: Path,
    trace_root: Path,
    model: str,
    generator: Generator | None,
    approver: Approver | None,
    taxonomy_check: bool,
    judge_call: JudgeCall | None,
    generation_threshold: int,
    activation_poll_seconds: float,
    activation_timeout_seconds: float,
) -> GenerationResult:
    try:
        traces = [trace.to_dict() for trace in workspace.pending.iter_traces()]
        if not traces:
            raise ValueError("no pending traces available for generation")
        raw = (
            generator(traces)
            if generator is not None
            else _atlas_generate(traces, model, _generation_output_dir(workspace))
        )
        candidate = candidate_from_atlas(raw, repo=workspace.repo)
        if taxonomy_check:
            try:
                check = check_taxonomy(
                    workspace,
                    candidate,
                    atlas_model=model,
                    judge_call=judge_call,
                )
            except Exception as exc:
                snapshot_count = latest_snapshot_count(workspace)
                workspace.mark_generation_rejected(
                    snapshot_count,
                    generation_threshold,
                    f"taxonomy check failed: {exc}",
                )
                if workspace.pending.count() >= snapshot_count + generation_threshold:
                    workspace.mark_generation("running")
                    return GenerationResult(
                        "retry_now",
                        "taxonomy check failed but enough new traces already "
                        "exist; regenerating immediately",
                    )
                return GenerationResult(
                    "rejected",
                    "taxonomy check failed; MAST remains active and retry "
                    f"requires {generation_threshold} new traces: {exc}",
                )
            candidate = check.candidate
            accepted = check.accepted
            snapshot_count = check.snapshot_count
            rejection_reason = check.reason
        else:
            accepted = structurally_accept(candidate)
            snapshot_count = workspace.pending.count()
            rejection_reason = "candidate failed structural acceptance"

        if accepted and approver is not None:
            accepted = approver(candidate)
            if not accepted:
                rejection_reason = "candidate rejected by approval callback"
        if not accepted:
            workspace.mark_generation_rejected(
                snapshot_count,
                generation_threshold,
                rejection_reason,
            )
            if workspace.pending.count() >= snapshot_count + generation_threshold:
                workspace.mark_generation("running")
                return GenerationResult(
                    "retry_now",
                    "candidate rejected but enough new traces already exist; "
                    "regenerating immediately",
                )
            return GenerationResult(
                "rejected",
                f"generated candidate was rejected ({rejection_reason}); "
                "pending traces were preserved",
            )
        taxonomy_id = _wait_and_commit(
            workspace,
            candidate,
            store_dir=Path(store_dir),
            trace_root=Path(trace_root),
            poll_seconds=activation_poll_seconds,
            timeout_seconds=activation_timeout_seconds,
        )
        return GenerationResult(
            "activated",
            "generated taxonomy approved and activated",
            taxonomy_id,
        )
    except Exception:
        raise


def _wait_and_commit(
    workspace: ProgramWorkspace,
    candidate: dict[str, Any],
    *,
    store_dir: Path,
    trace_root: Path,
    poll_seconds: float,
    timeout_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    while True:
        taxonomy_id = None
        with workspace.locked_manifest() as manifest:
            if not manifest.get("active_sessions"):
                taxonomy_id = _commit_accepted_candidate(
                    workspace,
                    manifest,
                    candidate,
                    store_dir=store_dir,
                    trace_root=trace_root,
                )
        if taxonomy_id:
            try:
                workspace.pending.integrate_into(
                    TraceStore(trace_root / taxonomy_id)
                )
            except OSError:
                # Activation is already durable. Pending duplicates are safer
                # than deleting unverified source data and are cleaned on a
                # later integration attempt.
                pass
            return taxonomy_id
        if time.monotonic() >= deadline:
            raise TimeoutError("timed out waiting for running tasks to finish")
        time.sleep(poll_seconds)


def _commit_accepted_candidate(
    workspace: ProgramWorkspace,
    manifest: dict[str, Any],
    candidate: dict[str, Any],
    *,
    store_dir: Path,
    trace_root: Path,
) -> str:
    taxonomy_id = _new_taxonomy_id(candidate)
    record = {"taxonomy_id": taxonomy_id, **candidate}
    staging = trace_root / f".staging-{taxonomy_id}-{uuid.uuid4().hex}"
    final_traces = trace_root / taxonomy_id
    registered = False
    final_created = False
    try:
        _copy_and_verify(workspace.pending.trace_files(), staging)
        trace_root.mkdir(parents=True, exist_ok=True)
        if final_traces.exists():
            raise FileExistsError(f"taxonomy trace folder already exists: {final_traces}")
        os.replace(staging, final_traces)
        final_created = True
        store.register(record, store_dir)
        registered = True
        manifest["taxonomy_id"] = taxonomy_id
        manifest["generation"] = {"state": "complete", "last_error": None}
    except Exception:
        if registered:
            store.unregister(taxonomy_id, store_dir)
        if final_created:
            shutil.rmtree(final_traces, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return taxonomy_id


def _copy_and_verify(sources: Iterable[Path], staging: Path) -> None:
    staging.mkdir(parents=True, exist_ok=False)
    for source in sources:
        payload = source.read_bytes()
        target = staging / source.name
        target.write_bytes(payload)
        if target.read_bytes() != payload:
            raise OSError(f"staged trace verification failed for {source}")


def _new_taxonomy_id(candidate: dict[str, Any]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(
        json.dumps(candidate, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:8]
    return f"tax-{stamp}-{digest}-{uuid.uuid4().hex[:6]}"


def _spawn_worker(trace_output: Path, store_dir: Path, trace_root: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "atlas_runtime.generation",
        "--worker",
        "--trace-output",
        str(trace_output),
        "--store-dir",
        str(store_dir),
        "--trace-root",
        str(trace_root),
    ]
    worker_log = Path(trace_output) / "generation_worker.log"
    worker_log.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(worker_log, "a", buffering=1, encoding="utf-8", errors="replace")
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_fh,
        "stderr": subprocess.STDOUT,
        "cwd": str(Path(__file__).resolve().parent.parent),
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--trace-output", required=True)
    parser.add_argument("--store-dir", required=True)
    parser.add_argument("--trace-root", required=True)
    args = parser.parse_args()
    if not args.worker:
        parser.error("--worker is required")
    workspace = ProgramWorkspace(args.trace_output)
    result = run_generation_job(
        workspace,
        store_dir=args.store_dir,
        trace_root=args.trace_root,
        atlas_model=workspace.load().get("atlas_model"),
    )
    return 0 if result.action == "activated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
