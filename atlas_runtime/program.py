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

    def try_begin_refinement(self, threshold: int) -> bool:
        with self.locked_manifest() as manifest:
            refinement = manifest.setdefault(
                "refinement",
                self._new_manifest()["refinement"],
            )
            if int(refinement.get("traces_since_refinement", 0)) < threshold:
                return False
            if refinement.get("state") == "running":
                return False
            refinement["state"] = "running"
            refinement["last_error"] = None
            return True

    def mark_refinement(self, state: str, error: str | None = None) -> None:
        with self.locked_manifest() as manifest:
            refinement = manifest.setdefault(
                "refinement",
                self._new_manifest()["refinement"],
            )
            refinement["state"] = state
            refinement["last_error"] = error

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

    def try_begin_generation(self) -> bool:
        with self.locked_manifest() as manifest:
            if manifest.get("taxonomy_id"):
                return False
            if manifest.get("generation", {}).get("state") == "running":
                return False
            generation = manifest.setdefault("generation", {})
            generation["state"] = "running"
            generation["last_error"] = None
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
