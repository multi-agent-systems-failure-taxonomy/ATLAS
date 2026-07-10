"""Program identity and manifest state anchored by mandatory trace_output."""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .repository import discover_repo
from .traces import TraceStore
from .worker_state import (
    DEFAULT_WORKER_STALE_AFTER_SECONDS,
    GENERATION_WORKER_STATE,
    REFINEMENT_WORKER_STATE,
    worker_state_is_stale,
)

MANIFEST_NAME = ".atlas-program.json"


class ProgramConflict(ValueError):
    """Raised when a run conflicts with the program's bound taxonomy."""


class ProgramWorkspace:
    """Stable program identity derived from a user-selected trace directory."""

    def __init__(
        self,
        trace_output: Path | str,
        *,
        repo: str | None = None,
        repo_path: Path | str | None = None,
    ) -> None:
        if trace_output is None or not str(trace_output).strip():
            raise ValueError("trace_output is required for every ATLAS run")
        self.root = Path(trace_output).expanduser().resolve()
        self.manifest_path = self.root / MANIFEST_NAME
        self.pending = TraceStore(self.root / "pending")
        self.root.mkdir(parents=True, exist_ok=True)
        discovered_repo = discover_repo(repo, repo_path)
        with self.locked_manifest() as manifest:
            if not manifest:
                manifest.update(self._new_manifest(discovered_repo))
            elif not manifest.get("repo"):
                manifest["repo"] = discovered_repo
            elif repo is not None and manifest["repo"] != discovered_repo:
                raise ProgramConflict(
                    f"program already records repo {manifest['repo']!r}, not "
                    f"{discovered_repo!r}"
                )

    @staticmethod
    def _new_manifest(repo: str = "") -> dict[str, Any]:
        return {
            "version": 1,
            "program_id": f"program-{uuid.uuid4()}",
            "repo": repo,
            "atlas_model": None,
            "taxonomy_id": None,
            "active_sessions": [],
            "generation": {
                "state": "idle",
                "last_error": None,
                "retry_after_count": 5,
                "last_check_snapshot_count": 0,
            },
            "refinement": {
                "rounds_completed": 0,
                "traces_since_refinement": 0,
                "trace_refs": [],
                "state": "idle",
                "last_error": None,
            },
            "usage": {
                "totals": {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                },
                "events": [],
            },
        }

    def load(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    @property
    def program_id(self) -> str:
        return str(self.load()["program_id"])

    @property
    def repo(self) -> str:
        return str(self.load().get("repo", ""))

    def register_session(self, session_id: str, taxonomy_id: str) -> None:
        with self.locked_manifest() as manifest:
            sessions = manifest.setdefault("active_sessions", [])
            sessions.append({"session_id": session_id, "taxonomy_id": taxonomy_id})

    def begin_session(
        self,
        session_id: str,
        requested_taxonomy_id: str | None,
        atlas_model: str | None = None,
    ) -> str:
        """Choose the program taxonomy and register a running task atomically."""
        with self.locked_manifest() as manifest:
            current = manifest.get("taxonomy_id")
            configured_model = manifest.get("atlas_model")
            if configured_model and atlas_model and configured_model != atlas_model:
                raise ProgramConflict(
                    f"program already uses ATLAS model {configured_model!r}, not "
                    f"{atlas_model!r}"
                )
            if atlas_model and not configured_model:
                manifest["atlas_model"] = atlas_model
            if current and requested_taxonomy_id and current != requested_taxonomy_id:
                raise ProgramConflict(
                    f"program already uses taxonomy {current!r}, not "
                    f"{requested_taxonomy_id!r}"
                )
            selected = current or requested_taxonomy_id or "mast"
            if requested_taxonomy_id and not current:
                manifest["taxonomy_id"] = requested_taxonomy_id
                manifest["generation"] = {
                    "state": "not_needed",
                    "last_error": None,
                }
            manifest.setdefault("active_sessions", []).append(
                {"session_id": session_id, "taxonomy_id": selected}
            )
            return str(selected)

    def follow_taxonomy_successor(self, taxonomy_id: str) -> None:
        """Advance taxonomy identity without touching program-local progress."""
        with self.locked_manifest() as manifest:
            manifest["taxonomy_id"] = taxonomy_id

    def add_refinement_traces(
        self,
        taxonomy_id: str,
        filenames: list[str],
    ) -> int:
        with self.locked_manifest() as manifest:
            refinement = manifest.setdefault(
                "refinement",
                self._new_manifest()["refinement"],
            )
            refs = refinement.setdefault("trace_refs", [])
            refs.extend(
                {"taxonomy_id": taxonomy_id, "filename": name}
                for name in filenames
            )
            refinement["traces_since_refinement"] = int(
                refinement.get("traces_since_refinement", 0)
            ) + len(filenames)
            return int(refinement["traces_since_refinement"])

    def refinement_state(self) -> dict[str, Any]:
        return dict(
            self.load().get("refinement")
            or self._new_manifest()["refinement"]
        )

    def try_begin_refinement(
        self,
        threshold: int,
        *,
        worker_kind: str = "inline",
        worker_stale_after_seconds: float = DEFAULT_WORKER_STALE_AFTER_SECONDS,
    ) -> bool:
        with self.locked_manifest() as manifest:
            refinement = manifest.setdefault(
                "refinement",
                self._new_manifest()["refinement"],
            )
            if int(refinement.get("traces_since_refinement", 0)) < threshold:
                return False
            if refinement.get("state") == "running":
                existing_kind = refinement.get("worker_kind")
                if existing_kind in (None, "background") and self._worker_is_stale(
                    refinement,
                    REFINEMENT_WORKER_STATE,
                    worker_stale_after_seconds,
                    legacy_without_timestamp_is_stale=existing_kind is None,
                ):
                    refinement["state"] = "failed"
                    refinement["last_error"] = (
                        "previous background refinement worker became stale"
                    )
                else:
                    return False
            refinement["state"] = "running"
            refinement["last_error"] = None
            refinement["worker_kind"] = worker_kind
            refinement["worker_started_unix"] = time.time()
            return True

    def mark_refinement(self, state: str, error: str | None = None) -> None:
        with self.locked_manifest() as manifest:
            refinement = manifest.setdefault(
                "refinement",
                self._new_manifest()["refinement"],
            )
            refinement["state"] = state
            refinement["last_error"] = error
            if state != "running":
                refinement.pop("worker_kind", None)
                refinement.pop("worker_started_unix", None)

    def complete_refinement(self, taxonomy_id: str) -> None:
        with self.locked_manifest() as manifest:
            refinement = manifest.setdefault(
                "refinement",
                self._new_manifest()["refinement"],
            )
            manifest["taxonomy_id"] = taxonomy_id
            refinement["rounds_completed"] = int(
                refinement.get("rounds_completed", 0)
            ) + 1
            refinement["traces_since_refinement"] = 0
            refinement["trace_refs"] = []
            refinement["state"] = "complete"
            refinement["last_error"] = None
            refinement.pop("worker_kind", None)
            refinement.pop("worker_started_unix", None)

    def record_usage_event(
        self,
        *,
        stage: str,
        model: str | None = None,
        provider: str | None = None,
        usage_available: bool = False,
        calls: int = 1,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append an honest learning-call usage event to the program manifest.

        Many supported transports do not expose token or cost metadata. In
        those cases ATLAS records the call and marks usage unavailable instead
        of inventing estimates.
        """
        event = {
            "timestamp_unix": time.time(),
            "stage": stage,
            "model": model,
            "provider": provider,
            "usage_available": bool(usage_available),
            "calls": int(calls),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "details": details or {},
        }
        with self.locked_manifest() as manifest:
            usage = manifest.setdefault("usage", self._new_manifest()["usage"])
            totals = usage.setdefault("totals", {})
            totals["calls"] = int(totals.get("calls", 0)) + event["calls"]
            for key, value in (
                ("input_tokens", input_tokens),
                ("output_tokens", output_tokens),
            ):
                if isinstance(value, int):
                    totals[key] = int(totals.get(key, 0)) + value
            if isinstance(cost_usd, int | float):
                totals["cost_usd"] = float(totals.get("cost_usd", 0.0)) + float(
                    cost_usd
                )
            totals.setdefault("input_tokens", 0)
            totals.setdefault("output_tokens", 0)
            totals.setdefault("cost_usd", 0.0)
            events = usage.setdefault("events", [])
            events.append(event)
            del events[:-200]

    def finish_session(self, session_id: str) -> None:
        with self.locked_manifest() as manifest:
            manifest["active_sessions"] = [
                item
                for item in manifest.get("active_sessions", [])
                if item.get("session_id") != session_id
            ]

    def bind_inherited_taxonomy(self, taxonomy_id: str) -> None:
        with self.locked_manifest() as manifest:
            current = manifest.get("taxonomy_id")
            if current and current != taxonomy_id:
                raise ProgramConflict(
                    f"program already uses taxonomy {current!r}, not {taxonomy_id!r}"
                )
            manifest["taxonomy_id"] = taxonomy_id
            manifest["generation"] = {
                "state": "not_needed",
                "last_error": None,
            }

    def generation_state(self) -> str:
        return str(self.load().get("generation", {}).get("state", "idle"))

    def mark_generation(self, state: str, error: str | None = None) -> None:
        with self.locked_manifest() as manifest:
            generation = manifest.setdefault("generation", {})
            generation["state"] = state
            generation["last_error"] = error
            if state != "running":
                generation.pop("worker_kind", None)
                generation.pop("worker_started_unix", None)

    def mark_generation_rejected(
        self,
        snapshot_count: int,
        threshold: int,
        error: str | None = None,
    ) -> None:
        with self.locked_manifest() as manifest:
            generation = manifest.setdefault("generation", {})
            generation["state"] = "rejected"
            generation["last_error"] = error
            generation["last_check_snapshot_count"] = snapshot_count
            generation["retry_after_count"] = snapshot_count + threshold
            generation.pop("worker_kind", None)
            generation.pop("worker_started_unix", None)

    def try_begin_generation(
        self,
        *,
        worker_kind: str = "inline",
        worker_stale_after_seconds: float = DEFAULT_WORKER_STALE_AFTER_SECONDS,
    ) -> bool:
        with self.locked_manifest() as manifest:
            if manifest.get("taxonomy_id"):
                return False
            generation = manifest.setdefault("generation", {})
            if generation.get("state") == "running":
                existing_kind = generation.get("worker_kind")
                if existing_kind in (None, "background") and self._worker_is_stale(
                    generation,
                    GENERATION_WORKER_STATE,
                    worker_stale_after_seconds,
                    legacy_without_timestamp_is_stale=existing_kind is None,
                ):
                    generation["state"] = "failed"
                    generation["last_error"] = (
                        "previous background generation worker became stale"
                    )
                else:
                    return False
            generation["state"] = "running"
            generation["last_error"] = None
            generation["worker_kind"] = worker_kind
            generation["worker_started_unix"] = time.time()
            return True

    def generation_retry_after(self, default: int) -> int:
        return int(
            self.load().get("generation", {}).get("retry_after_count", default)
        )

    def activate_if_idle(self, taxonomy_id: str) -> bool:
        """Atomically activate only when no task is running."""
        with self.locked_manifest() as manifest:
            if manifest.get("active_sessions"):
                return False
            if manifest.get("taxonomy_id"):
                return manifest["taxonomy_id"] == taxonomy_id
            manifest["taxonomy_id"] = taxonomy_id
            manifest["generation"] = {"state": "complete", "last_error": None}
            return True

    def _worker_is_stale(
        self,
        job: dict[str, Any],
        filename: str,
        stale_after_seconds: float,
        *,
        legacy_without_timestamp_is_stale: bool,
    ) -> bool:
        worker_path = self.root / filename
        if worker_path.exists():
            return worker_state_is_stale(
                worker_path,
                stale_after_seconds=stale_after_seconds,
                missing_is_stale=False,
            )
        started = job.get("worker_started_unix")
        if isinstance(started, int | float):
            return time.time() - float(started) > stale_after_seconds
        return legacy_without_timestamp_is_stale

    @contextmanager
    def locked_manifest(self, *, timeout: float = 5.0, stale_after: float = 60.0):
        lock = self.root / ".manifest.lock"
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
                    raise TimeoutError(f"timed out waiting for program lock {lock}")
                time.sleep(0.05)
        manifest = self.load()
        try:
            yield manifest
            temporary = self.root / f".{MANIFEST_NAME}.tmp"
            temporary.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.manifest_path)
        finally:
            try:
                lock.rmdir()
            except FileNotFoundError:
                pass
