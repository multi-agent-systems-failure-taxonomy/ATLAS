"""Generate and store an inheritable taxonomy from user-supplied traces.

The upstream ATLAS loader and eight-stage pipeline own trace normalization and
taxonomy induction. This module adds atlas_skill lifecycle semantics:

* canonical ``GenerationTrace`` validation;
* the existing support-based taxonomy check;
* unique taxonomy ID allocation;
* transactional taxonomy + trace registration;
* no program binding or automatic activation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from finding import store
from vendor.atlas import generate_taxonomy as upstream_generate_taxonomy
from vendor.atlas import load_traces

from .generation import candidate_from_atlas
from .learning_calls import outcome_blind_trace
from .program import ProgramWorkspace
from .repository import discover_repo
from .taxonomy_check import JudgeCall, TaxonomyCheckResult, check_taxonomy
from .traces import DEFAULT_TRACE_ROOT, GenerationTrace, TraceStore

Generator = Callable[[list[dict[str, Any]]], dict[str, Any]]


@dataclass(frozen=True)
class ImportedTaxonomyResult:
    taxonomy_id: str
    trace_count: int
    active_codes: tuple[str, ...]
    taxonomy_path: Path
    trace_path: Path
    artifacts_path: Path

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        for field in ("taxonomy_path", "trace_path", "artifacts_path"):
            record[field] = str(record[field])
        record["active_codes"] = list(self.active_codes)
        return record


def generate_imported_taxonomy(
    traces: Path | str | Iterable[Any],
    *,
    atlas_model: str,
    store_dir: Path | str = store.DEFAULT_STORE_DIR,
    trace_root: Path | str = DEFAULT_TRACE_ROOT,
    repo: str | None = None,
    repo_path: Path | str | None = None,
    max_codes: int = 0,
    taxonomy_check: bool = True,
    skip_judge: bool = False,
    save_intermediate: bool = True,
    verbose: bool = True,
    generator: Generator | None = None,
    judge_call: JudgeCall | None = None,
) -> ImportedTaxonomyResult:
    """Generate, validate, and register a dormant taxonomy for later inheritance.

    ``skip_judge=True`` bypasses the post-generation Selection Judge check
    regardless of ``taxonomy_check``. Reserved for the future end-of-generation
    reflection-judge refinement path too.
    """
    if not str(atlas_model).strip():
        raise ValueError("atlas_model is required")
    if max_codes < 0:
        raise ValueError("max_codes cannot be negative")

    canonical = _load_canonical_traces(traces, verbose=verbose)
    store_dir = Path(store_dir).expanduser().resolve()
    trace_root = Path(trace_root).expanduser().resolve()
    display_repo = discover_repo(repo, repo_path)
    staging_parent = store_dir / "_state"
    staging_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=".import-staging-",
        dir=staging_parent,
    ) as temporary:
        staging = Path(temporary)
        generation_dir = staging / "generation"
        generation_traces = [
            outcome_blind_trace(trace.to_dict())
            for trace in canonical
        ]
        raw = (
            generator(generation_traces)
            if generator is not None
            else upstream_generate_taxonomy(
                traces=generation_traces,
                output_dir=generation_dir,
                model=atlas_model,
                max_codes=max_codes,
                save_intermediate=save_intermediate,
                verbose=verbose,
            )
        )
        candidate = candidate_from_atlas(raw, repo=display_repo)
        check = _check_candidate(
            staging,
            canonical,
            candidate,
            atlas_model=atlas_model,
            enabled=taxonomy_check and not skip_judge,
            judge_call=judge_call,
        )
        if not check.accepted:
            raise ValueError(
                "generated taxonomy was rejected: "
                f"{check.reason}; no taxonomy was stored"
            )

        taxonomy_id = _new_taxonomy_id(check.candidate)
        record = {"taxonomy_id": taxonomy_id, **check.candidate}
        taxonomy_path, trace_path = _commit(
            record,
            canonical,
            store_dir=store_dir,
            trace_root=trace_root,
        )
        artifacts_path = store_dir / "_state" / "imports" / taxonomy_id
        try:
            _persist_artifacts(
                staging,
                artifacts_path,
                source=traces,
                atlas_model=atlas_model,
                trace_count=len(canonical),
                check=check,
            )
        except Exception:
            store.unregister(taxonomy_id, store_dir)
            shutil.rmtree(trace_path, ignore_errors=True)
            raise
        return ImportedTaxonomyResult(
            taxonomy_id=taxonomy_id,
            trace_count=len(canonical),
            active_codes=tuple(check.active_codes),
            taxonomy_path=taxonomy_path,
            trace_path=trace_path,
            artifacts_path=artifacts_path,
        )


def _load_canonical_traces(
    source: Path | str | Iterable[Any],
    *,
    verbose: bool,
) -> list[GenerationTrace]:
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.is_file() and path.suffix.lower() not in {".json", ".jsonl"}:
            loaded = load_traces([path.read_text(encoding="utf-8")], verbose=verbose)
        else:
            loaded = load_traces(source, verbose=verbose)
    else:
        loaded = load_traces(source, verbose=verbose)
    canonical: list[GenerationTrace] = []
    for record in loaded:
        try:
            canonical.append(
                GenerationTrace(
                    problem_id=str(record.get("problem_id", "")).strip(),
                    task=str(record.get("task", "")),
                    raw_trajectory=str(record.get("raw_trajectory", "")),
                    metadata=dict(record.get("metadata") or {}),
                )
            )
        except (TypeError, ValueError):
            continue
    if not canonical:
        raise ValueError(
            "no valid traces could be loaded; provide a supported JSON, JSONL, "
            "directory, conversation, Codex, event-log, KIRA, tau-bench, or "
            "canonical ATLAS trace source"
        )
    return canonical


def _check_candidate(
    staging: Path,
    traces: list[GenerationTrace],
    candidate: dict[str, Any],
    *,
    atlas_model: str,
    enabled: bool,
    judge_call: JudgeCall | None,
) -> TaxonomyCheckResult:
    workspace = ProgramWorkspace(staging / "validation-program", repo="import")
    workspace.pending.append_many(traces)
    if enabled:
        return check_taxonomy(
            workspace,
            candidate,
            atlas_model=atlas_model,
            judge_call=judge_call,
        )
    active = sorted(str(code["id"]) for code in candidate["codes"])
    return TaxonomyCheckResult(
        accepted=True,
        candidate=candidate,
        snapshot_count=len(traces),
        active_codes=active,
        annotations=[],
        failed_units=0,
        reason="taxonomy check disabled by caller",
    )


def _commit(
    record: dict[str, Any],
    traces: list[GenerationTrace],
    *,
    store_dir: Path,
    trace_root: Path,
) -> tuple[Path, Path]:
    taxonomy_id = str(record["taxonomy_id"])
    staging = trace_root / f".staging-{taxonomy_id}-{uuid.uuid4().hex}"
    final_traces = trace_root / taxonomy_id
    taxonomy_path: Path | None = None
    final_created = False
    try:
        TraceStore(staging).append_many(traces)
        trace_root.mkdir(parents=True, exist_ok=True)
        if final_traces.exists():
            raise FileExistsError(
                f"taxonomy trace folder already exists: {final_traces}"
            )
        os.replace(staging, final_traces)
        final_created = True
        taxonomy_path = store.register(record, store_dir)
        return taxonomy_path, final_traces
    except Exception:
        if taxonomy_path is not None:
            store.unregister(taxonomy_id, store_dir)
        if final_created:
            shutil.rmtree(final_traces, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _persist_artifacts(
    staging: Path,
    destination: Path,
    *,
    source: Any,
    atlas_model: str,
    trace_count: int,
    check: TaxonomyCheckResult,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}-{uuid.uuid4().hex}.tmp"
    temporary.mkdir()
    try:
        generation = staging / "generation"
        validation = staging / "validation-program" / "checks"
        if generation.exists():
            shutil.copytree(generation, temporary / "generation")
        if validation.exists():
            shutil.copytree(validation, temporary / "checks")
        (temporary / "import.json").write_text(
            json.dumps(
                {
                    "source": (
                        str(source)
                        if isinstance(source, (str, Path))
                        else "iterable"
                    ),
                    "atlas_model": atlas_model,
                    "trace_count": trace_count,
                    "taxonomy_check": {
                        "accepted": check.accepted,
                        "active_codes": list(check.active_codes),
                        "failed_units": check.failed_units,
                        "reason": check.reason,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _new_taxonomy_id(candidate: dict[str, Any]) -> str:
    import hashlib

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(
        json.dumps(candidate, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:8]
    return f"tax-{stamp}-{digest}-{uuid.uuid4().hex[:6]}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate and store an inheritable ATLAS taxonomy from user traces."
        )
    )
    parser.add_argument("--traces", required=True)
    parser.add_argument("--atlas-model", required=True)
    parser.add_argument("--store-dir", default=store.DEFAULT_STORE_DIR)
    parser.add_argument("--trace-root", default=DEFAULT_TRACE_ROOT)
    parser.add_argument("--repo")
    parser.add_argument("--repo-path")
    parser.add_argument("--max-codes", type=int, default=0)
    parser.add_argument(
        "--taxonomy-check",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        default=False,
        help=(
            "skip the judge + refinement step at the end of generation. "
            "Overrides --taxonomy-check and also bypasses reflection-judge "
            "refinement when that path is wired in"
        ),
    )
    parser.add_argument("--no-intermediate", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = generate_imported_taxonomy(
            args.traces,
            atlas_model=args.atlas_model,
            store_dir=args.store_dir,
            trace_root=args.trace_root,
            repo=args.repo,
            repo_path=args.repo_path,
            max_codes=args.max_codes,
            taxonomy_check=args.taxonomy_check,
            skip_judge=args.skip_judge,
            save_intermediate=not args.no_intermediate,
            verbose=not args.quiet,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
