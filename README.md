# atlas_skill — Taxonomy Finding

The first step of ATLAS: **resolve which taxonomy a run inherits.** It returns a
`taxonomy_id` or the literal `none` (start from 0). It does **not** load full
taxonomy content for use — that is Render, a later step.

## Data model

A taxonomy is a first-class record uniquely identified by its **`taxonomy_id`** —
the single organizing concept. Each record carries:

| field         | role                                                            |
|---------------|-----------------------------------------------------------------|
| `taxonomy_id` | unique identity / key — the only thing that selects a record    |
| `repo`        | **recorded, display-only** — routes and groups nothing          |
| `domain`      | **recorded, display-only** — set at generation (a later step)   |
| `codes`       | the failure modes (code number, name, explanation, any fields)  |

`repo` and `domain` are inert columns. There is **no** bucket key, fallback walk,
`task_type`, `stack`, or facet routing anywhere — `taxonomy_id` is everything.

## Store

A flat store: **one JSON file per taxonomy** at `taxonomies/<taxonomy_id>.json`.

> **Format choice (flagged):** one JSON file per record, filename = `taxonomy_id`.
> `list_all` globs the directory and reads only the three header fields
> (`taxonomy_id`, `repo`, `domain`); `fetch_by_id` reads the single matching file
> for the full record. Chosen over a single JSONL file so each taxonomy is an
> independent, human-diffable unit and writes never rewrite a shared file.

Two operations (`finding/store.py`):
- `list_all(store_dir)` → `[{taxonomy_id, repo, domain}, ...]`, global across repos
- `fetch_by_id(taxonomy_id, store_dir)` → full record, or `TaxonomyNotFound`

## Taxonomy Finding — the three `--inherit` forms

| invocation                  | behavior                                              |
|-----------------------------|-------------------------------------------------------|
| `python -m finding`         | no `--inherit` → prints `none`. No UI.                |
| `python -m finding --inherit <id>` | returns that id; **missing id → error (exit 2)**, never a silent none. No UI. |
| `python -m finding --inherit`      | (no id) → blocking localhost **web picker** |

### Web picker (`--inherit`, no id)

A blocking localhost web view:
- a table with exactly 3 columns — `repo`, `taxonomy_id`, `domain` — **global
  across all repos** (cross-repo picking allowed)
- click a row → detail view of that taxonomy's **full content** (every code:
  number, failure-mode name, explanation, and any extra fields)
- a **"use none / start from 0"** option

It returns the chosen `taxonomy_id` (or `none`) to stdout, then completes.

## Run

```sh
python -m finding                              # -> none
python -m finding --inherit tax-django-orm-001 # -> tax-django-orm-001
python -m finding --inherit                    # -> opens picker, blocks
```

## Tests

```sh
python -m unittest discover -s tests -t . -v
```

Covers: no-inherit→none; `--inherit <existing>`→id; `--inherit <missing>`→error;
`list_all` reads the 3 fields; `fetch_by_id` returns the full record; the
none-selection path; and the web view (table columns, detail content, choose).
Tests run against the real fixtures in `taxonomies/`.

## Scope

This repo is **only** Taxonomy Finding. No engine, render, deliver, or learning
loop — those are later, separate steps. Stdlib only (no dependencies).
