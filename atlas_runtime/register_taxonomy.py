"""Register an externally-generated taxonomy file under a new id.

``atlas-register-taxonomy`` is the symmetric companion to
``atlas-import-traces``: where the latter generates a taxonomy *from* user
traces, this one accepts a taxonomy.json the user already has in hand
(produced by a custom pipeline, hand-edited, copied from a sibling project,
etc.), validates its shape, optionally runs the Reflection Judge + refiner
against supporting traces, and registers it in the store.

Two accepted input shapes:

  1. Flat schema (``{repo, domain, codes: [...]}``) — atlas_skill's own
     internal format. Used verbatim.
  2. ATLAS pipeline output (``{annotation_layer, full_layer, ...}``) —
     converted via Taxonomy.from_dict round-trip.

Without ``--traces``, no judge runs — the candidate is registered as-is
after structural validation (the same validation atlas-import-traces uses
under ``--skip-judge``). With ``--traces``, the Reflection Judge + refiner
runs over the provided trace JSONL (oracle-blind projection applied) and
the refined taxonomy is registered instead of the original.

The repo/domain fields are taken from the input file unless overridden
by ``--repo`` / ``--domain``. The taxonomy_id is auto-allocated in the
same shape ``atlas-import-traces`` uses (``tax-<stamp>-<digest>-<uuid>``)
unless ``--id`` is supplied, in which case that exact id is used (letters,
digits, dots, underscores, hyphens only; ``mast`` is reserved).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from finding import store
from vendor.atlas import load_traces

from .generation import candidate_from_atlas
from .reflection_refinement import RefinementSummary, refine_with_reflection_judge
from .repository import discover_repo
from .taxonomy_data import Taxonomy
from .traces import DEFAULT_TRACE_ROOT, GenerationTrace, TraceStore


@dataclass(frozen=True)
class RegisteredTaxonomyResult:
    taxonomy_id: str
    taxonomy_path: Path
    trace_count: int
    refinement: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["taxonomy_path"] = str(record["taxonomy_path"])
        return record


def load_candidate(taxonomy_path: Path) -> dict[str, Any]:
    """Read a taxonomy.json from disk and return atlas_skill's flat candidate shape.

    Accepts both atlas_skill flat (``{repo, domain, codes}``) and ATLAS
    pipeline output (``{annotation_layer, full_layer}``).
    """
    data = json.loads(Path(taxonomy_path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(
            f"{taxonomy_path}: top-level must be a JSON object (got {type(data).__name__})"
        )

    if "codes" in data and isinstance(data.get("codes"), list):
        # Already flat.
        return {
            "repo": str(data.get("repo", "") or ""),
            "domain": str(data.get("domain", "") or ""),
            "codes": data["codes"],
        }

    if "annotation_layer" in data or "full_layer" in data:
        # ATLAS pipeline output — round-trip via Taxonomy then flatten.
        tax = Taxonomy.from_dict(data)
        return _taxonomy_to_flat(tax)

    raise ValueError(
        f"{taxonomy_path}: unrecognized taxonomy shape — expected either "
        f"a flat {{repo, domain, codes}} object or an ATLAS pipeline "
        f"output with annotation_layer/full_layer"
    )


def _taxonomy_to_flat(taxonomy: Taxonomy) -> dict[str, Any]:
    """Render a Taxonomy back to atlas_skill's flat ``{repo, domain, codes}`` shape."""
    codes: list[dict[str, Any]] = []
    for c in taxonomy.codes:
        entry: dict[str, Any] = {
            "id": c.code,
            "name": c.name,
            "description": c.definition,
            "category": c.category,
        }
        if c.severity and c.severity != "major":
            entry["severity"] = c.severity
        if c.category == "B" and c.applies_to_role:
            entry["applies_to_role"] = c.applies_to_role
        if c.detection_heuristics:
            entry["detection_heuristics"] = list(c.detection_heuristics)
        codes.append(entry)
    return {
        "repo": taxonomy.metadata.get("repo", "") or "",
        "domain": taxonomy.metadata.get("domain", "") or "",
        "codes": codes,
    }


def register_taxonomy_file(
    taxonomy_path: Path | str,
    *,
    store_dir: Path | str = store.DEFAULT_STORE_DIR,
    trace_root: Path | str = DEFAULT_TRACE_ROOT,
    repo: str | None = None,
    repo_path: Path | str | None = None,
    domain: str | None = None,
    taxonomy_id: str | None = None,
    traces: Path | str | Iterable[Any] | None = None,
    atlas_model: str | None = None,
    judge_call: Callable[..., Any] | None = None,
    refiner_call: Callable[..., Any] | None = None,
) -> RegisteredTaxonomyResult:
    """Register a pre-generated taxonomy file.

    See module docstring for accepted input shapes.

    When ``traces`` is provided AND ``atlas_model`` is set, the Reflection
    Judge + refiner runs against the trace pool and the refined candidate is
    registered. Otherwise the candidate is registered as-is after structural
    validation.
    """
    taxonomy_path = Path(taxonomy_path).expanduser().resolve()
    if not taxonomy_path.is_file():
        raise FileNotFoundError(f"taxonomy file not found: {taxonomy_path}")

    candidate = load_candidate(taxonomy_path)
    if repo is None:
        candidate["repo"] = candidate["repo"] or discover_repo(None, repo_path)
    else:
        candidate["repo"] = repo
    if domain is not None:
        candidate["domain"] = domain

    refinement_block: dict[str, Any] = {"applied": False}
    canonical: list[GenerationTrace] = []
    if traces is not None:
        if not atlas_model:
            raise ValueError(
                "--traces was supplied but no --atlas-model was given; the "
                "Reflection Judge needs a model id"
            )
        canonical = _load_canonical_traces(traces)
        trace_dicts = [t.to_dict() for t in canonical]
        summary = refine_with_reflection_judge(
            candidate,
            trace_dicts,
            atlas_model=atlas_model,
            judge_call=judge_call,
            refiner_call=refiner_call,
        )
        candidate = summary.candidate
        refinement_block = _summary_to_block(summary)

    if not (isinstance(candidate, dict)
            and isinstance(candidate.get("codes"), list)
            and candidate["codes"]):
        raise ValueError(
            "taxonomy is structurally invalid (empty or missing codes); "
            "nothing was stored"
        )

    final_id = taxonomy_id or _new_taxonomy_id(candidate)
    record = {"taxonomy_id": final_id, **candidate}
    store_dir = Path(store_dir).expanduser().resolve()
    trace_root = Path(trace_root).expanduser().resolve()

    taxonomy_store_path: Path | None = None
    trace_committed = False
    try:
        if canonical:
            trace_destination = trace_root / final_id
            if trace_destination.exists():
                raise FileExistsError(
                    f"taxonomy trace folder already exists: {trace_destination}"
                )
            staging = trace_root / f".staging-{final_id}-{uuid.uuid4().hex}"
            TraceStore(staging).append_many(canonical)
            trace_root.mkdir(parents=True, exist_ok=True)
            staging.replace(trace_destination)
            trace_committed = True
        taxonomy_store_path = store.register(record, store_dir)
    except Exception:
        if taxonomy_store_path is not None:
            store.unregister(final_id, store_dir)
        if trace_committed:
            import shutil
            shutil.rmtree(trace_root / final_id, ignore_errors=True)
        raise

    return RegisteredTaxonomyResult(
        taxonomy_id=final_id,
        taxonomy_path=taxonomy_store_path,
        trace_count=len(canonical),
        refinement=refinement_block,
    )


def _summary_to_block(summary: RefinementSummary) -> dict[str, Any]:
    return {
        "applied": True,
        "n_traces_judged": summary.n_traces_judged,
        "retired": summary.retired,
        "added": summary.added,
        "edited": summary.edited,
        "split": summary.split,
        "n_proposed_names_distinct": summary.n_proposed_names_distinct,
        "n_weak_mapping_codes": summary.n_weak_mapping_codes,
        "n_unused_codes_in_sample": summary.n_unused_codes_in_sample,
        "judge_warnings": summary.judge_warnings,
    }


def _load_canonical_traces(source: Path | str | Iterable[Any]) -> list[GenerationTrace]:
    if isinstance(source, (str, Path)):
        loaded = load_traces(source, verbose=False)
    else:
        loaded = load_traces(source, verbose=False)
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
            "no valid traces could be loaded from the supplied source"
        )
    return canonical


def _new_taxonomy_id(candidate: dict[str, Any]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(
        json.dumps(candidate, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:8]
    return f"tax-{stamp}-{digest}-{uuid.uuid4().hex[:6]}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Register a pre-generated taxonomy.json under a new id.",
    )
    parser.add_argument(
        "--file",
        required=True,
        help="path to the taxonomy.json to register (flat or ATLAS pipeline shape)",
    )
    parser.add_argument(
        "--store-dir",
        default=str(store.DEFAULT_STORE_DIR),
        help="taxonomy store directory (default: $ATLAS_HOME/taxonomies/)",
    )
    parser.add_argument(
        "--trace-root",
        default=str(DEFAULT_TRACE_ROOT),
        help="trace root used only when --traces is supplied",
    )
    parser.add_argument("--repo", help="display-only repository label")
    parser.add_argument("--repo-path", help="repo path used to derive display metadata")
    parser.add_argument("--domain", help="domain label; overrides any domain in the file")
    parser.add_argument(
        "--id",
        dest="taxonomy_id",
        help="explicit taxonomy_id (filesystem-safe); default is an auto-allocated "
             "tax-<stamp>-<digest>-<uuid>",
    )
    parser.add_argument(
        "--traces",
        help="optional JSONL of supporting traces; when set, the Reflection Judge "
             "+ refiner runs and the refined taxonomy is registered",
    )
    parser.add_argument(
        "--atlas-model",
        help="model id used by the Reflection Judge + refiner; required iff --traces is set",
    )
    args = parser.parse_args(argv)

    try:
        result = register_taxonomy_file(
            args.file,
            store_dir=args.store_dir,
            trace_root=args.trace_root,
            repo=args.repo,
            repo_path=args.repo_path,
            domain=args.domain,
            taxonomy_id=args.taxonomy_id,
            traces=args.traces,
            atlas_model=args.atlas_model,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
