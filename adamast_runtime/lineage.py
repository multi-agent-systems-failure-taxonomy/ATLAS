"""Global taxonomy successor links, independent of program counters."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

from .fsio import read_text_retry, write_text_atomic_retry

STATE_DIR = "_state"
SUCCESSORS_FILE = "successors.json"


class TaxonomyLineage:
    def __init__(self, store_dir: Path | str) -> None:
        self.root = Path(store_dir) / STATE_DIR
        self.path = self.root / SUCCESSORS_FILE

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(read_text_retry(self.path))

    def resolve_latest(self, taxonomy_id: str) -> str:
        links = self.load()
        current = taxonomy_id
        seen: set[str] = set()
        while current in links:
            if current in seen:
                raise ValueError(f"taxonomy successor cycle at {current!r}")
            seen.add(current)
            current = links[current]
        return current

    def add_successor(self, old_id: str, new_id: str) -> None:
        with self.locked() as links:
            existing = links.get(old_id)
            if existing and existing != new_id:
                raise ValueError(
                    f"taxonomy {old_id!r} already has successor {existing!r}"
                )
            links[old_id] = new_id

    def remove_successor(self, old_id: str, new_id: str) -> None:
        with self.locked() as links:
            if links.get(old_id) == new_id:
                del links[old_id]

    @contextmanager
    def locked(self, *, timeout: float = 5.0, stale_after: float = 60.0):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = self.root / ".lineage.lock"
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
                    raise TimeoutError(f"timed out waiting for lineage lock {lock}")
                time.sleep(0.05)
        links = self.load()
        try:
            yield links
            write_text_atomic_retry(
                self.path,
                json.dumps(links, indent=2, ensure_ascii=False) + "\n",
            )
        finally:
            try:
                lock.rmdir()
            except FileNotFoundError:
                pass
