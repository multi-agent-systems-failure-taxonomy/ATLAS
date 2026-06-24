# finding/

ATLAS Taxonomy Finding: the taxonomy store + picker + MAST loader. Owns
the on-disk flat-JSON taxonomy format (one file per taxonomy keyed by
`taxonomy_id`), the `--inherit` resolver, the built-in MAST floor, and
the interactive web picker.

Configured via `ATLAS_HOME` (default `~/.atlas-skill/`); the store lives
under `$ATLAS_HOME/taxonomies/`.

## Programs

| File | Purpose |
|---|---|
| [`__init__.py`](__init__.py) | Public API exports |
| [`__main__.py`](__main__.py) | Lets `python -m finding` route to the CLI |
| [`cli.py`](cli.py) | `atlas-find` CLI: list / show / resolve / register taxonomies |
| [`mast.py`](mast.py) | Built-in MAST floor taxonomy (Cemri et al., 2025) — used as the fallback when no other taxonomy is inherited |
| [`resolver.py`](resolver.py) | `--inherit` resolver implementing the three forms: absent (none), `<id>` (explicit), bare `--inherit` (interactive picker) |
| [`store.py`](store.py) | Flat-JSON store: one file per taxonomy, atomic register/unregister, list_all, fetch_by_id, schema validation |
| [`webview.py`](webview.py) | Blocking localhost web view for the interactive `--inherit` (no id) form — the user picks a taxonomy in a browser tab and the call returns the chosen id |

## Bundled data

- `mast.json` — the MAST floor taxonomy data file shipped alongside `mast.py`.
