# finding/

ATLAS Taxonomy Finding: the taxonomy store + picker + MAST loader. Owns
the on-disk flat-JSON taxonomy format (one file per taxonomy keyed by
`taxonomy_id`), the inheritance resolver, the built-in MAST floor, and the
interactive web picker.

Configured via `ATLAS_HOME` (default `~/.atlas-skill/`); the store lives
under `$ATLAS_HOME/taxonomies/`.

## Programs

| File | Purpose |
|---|---|
| [`__init__.py`](__init__.py) | Public API exports |
| [`__main__.py`](__main__.py) | Lets `python -m finding` route to the CLI |
| [`cli.py`](cli.py) | `atlas-find` CLI: list / show / resolve / register taxonomies |
| [`mast.py`](mast.py) | Built-in MAST floor taxonomy (Cemri et al., 2025) — used as the fallback when no other taxonomy is inherited |
| [`resolver.py`](resolver.py) | Inheritance resolver implementing absent (none), explicit `<taxonomy_id>`, and interactive picker selection |
| [`store.py`](store.py) | Flat-JSON store: one file per taxonomy, atomic register/unregister, list_all, fetch_by_id, schema validation |
| [`webview.py`](webview.py) | Blocking localhost web view for `--inherit-pick`; the user picks a taxonomy in a browser tab and the call returns the chosen id |

## Bundled data

- `mast.json` — the MAST floor taxonomy data file shipped alongside `mast.py`.

## `taxonomy_id` format

A `taxonomy_id` is a filesystem-safe string (letters, digits, `.`, `_`, `-`)
used as the basename of the on-disk record (`<store-dir>/<taxonomy_id>.json`)
and as the directory name under the trace root. Reserved: the literal
string `mast` is the built-in MAST floor and cannot be used as a stored id.

When auto-allocated (by `atlas-import-traces`, `atlas-register-taxonomy`,
or end-of-generation activation), ids take the shape:

```
tax-<UTC-stamp>-<digest>-<uuid>
   e.g. tax-20260624T203104Z-7cf91f62-56ac5e
```

- `<UTC-stamp>` — `YYYYMMDD'T'HHMMSS'Z'`, the moment the id was minted.
- `<digest>` — first 8 hex chars of `sha256(record_json_sorted)`; lets
  you spot two identical taxonomies coming out of independent runs.
- `<uuid>` — first 6 hex chars of a uuid4; collision-breaker.

The `tax-` prefix is a convention, not a requirement — when registering
with `atlas-register-taxonomy --id <id>` you can pass any filesystem-safe
string (except `mast`). Auto-allocators always use the `tax-...` shape so
downstream tooling can filter on it cheaply.

`display_name` is the optional human-facing alias shown by selectors and the
browser catalog. It can change without changing `taxonomy_id`; older records
without it fall back to their `domain`. Native learning workers propose a short
display name for newly generated taxonomy records.
