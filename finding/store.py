"""Flat taxonomy store: one JSON file per taxonomy, keyed by taxonomy_id.

Layout::

    taxonomies/
        <taxonomy_id>.json   # exactly one record per taxonomy

A record carries: taxonomy_id, repo, domain, codes (failure modes).
`repo` and `domain` are recorded display-only fields; only taxonomy_id
identifies, looks up, or selects a record.

Two operations are supported:
  * list_all   -> the light triple (taxonomy_id, repo, domain) per record
  * fetch_by_id -> the full record (all codes and their fields)
"""

from __future__ import annotations

import json
from pathlib import Path

# Default store dir lives next to the package, at the repo root: <root>/taxonomies
DEFAULT_STORE_DIR = Path(__file__).resolve().parent.parent / "taxonomies"

# The three header fields surfaced by list_all (and the web-view table).
HEADER_FIELDS = ("taxonomy_id", "repo", "domain")


class TaxonomyNotFound(Exception):
    """Raised when a taxonomy_id has no record in the store."""

    def __init__(self, taxonomy_id: str):
        self.taxonomy_id = taxonomy_id
        super().__init__(f"no taxonomy with id {taxonomy_id!r} found in store")


def _record_path(taxonomy_id: str, store_dir) -> Path:
    return Path(store_dir) / f"{taxonomy_id}.json"


def exists(taxonomy_id: str, store_dir=DEFAULT_STORE_DIR) -> bool:
    """True iff a record file for `taxonomy_id` exists in the store."""
    return _record_path(taxonomy_id, store_dir).is_file()


def list_all(store_dir=DEFAULT_STORE_DIR) -> list[dict]:
    """Return [{taxonomy_id, repo, domain}, ...] for every record.

    Global across all repos — repo is just a column, not a partition.
    Sorted by taxonomy_id for stable display.
    """
    store_dir = Path(store_dir)
    records: list[dict] = []
    for path in sorted(store_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        records.append({field: data.get(field) for field in HEADER_FIELDS})
    records.sort(key=lambda r: r["taxonomy_id"] or "")
    return records


def fetch_by_id(taxonomy_id: str, store_dir=DEFAULT_STORE_DIR) -> dict:
    """Return the full record for `taxonomy_id`, or raise TaxonomyNotFound."""
    path = _record_path(taxonomy_id, store_dir)
    if not path.is_file():
        raise TaxonomyNotFound(taxonomy_id)
    return json.loads(path.read_text(encoding="utf-8"))
