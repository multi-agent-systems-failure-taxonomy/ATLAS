"""Taxonomy Finding resolver.

Resolves WHICH taxonomy a run inherits. Returns a taxonomy_id string, or
the literal "none". It does NOT load full taxonomy content for use — that
is Render, a later step.

The `--inherit` flag arrives in one of three forms, modelled by two
sentinels produced by the CLI parser:

  * ABSENT  (flag not given)            -> "none"
  * <id>    (flag given with a value)   -> that id, or error if missing
  * NO_ID   (flag given with no value)  -> launch blocking web view

`resolve()` returns the Finding decision: an id, or the literal "none".
"""

from __future__ import annotations

from . import store

NONE = "none"

# Sentinels for argparse: distinct from any real taxonomy_id string.
ABSENT = object()   # --inherit not present at all
NO_ID = object()    # --inherit present with no value -> interactive picker


def resolve(inherit, store_dir=store.DEFAULT_STORE_DIR, launcher=None) -> str:
    """Resolve the inherit request to a taxonomy_id or "none".

    Parameters
    ----------
    inherit:
        ABSENT, NO_ID, or an explicit taxonomy_id string.
    store_dir:
        Where the flat store lives.
    launcher:
        Callable(store_dir) -> taxonomy_id | "none". Used only for the
        NO_ID (interactive) form; injected so tests need no browser.

    Raises
    ------
    store.TaxonomyNotFound
        When an explicit id has no record (never a silent "none").
    """
    # Form 1: no --inherit -> start from 0.
    if inherit is ABSENT:
        return NONE

    # Form 3: --inherit with no id -> blocking web picker.
    if inherit is NO_ID:
        if launcher is None:
            raise RuntimeError("interactive --inherit requires a web-view launcher")
        chosen = launcher(store_dir)
        return chosen if chosen else NONE

    # Form 2: --inherit <taxonomy_id> -> that id, validated.
    taxonomy_id = inherit
    if not store.exists(taxonomy_id, store_dir):
        raise store.TaxonomyNotFound(taxonomy_id)
    return taxonomy_id
