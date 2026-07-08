# Taxonomies

ATLAS taxonomies are selected by one key: `taxonomy_id`.

`repo` and `domain` are display metadata. They do not route, group, or select taxonomies.

## Record shape

```json
{
  "taxonomy_id": "my-taxonomy-v1",
  "repo": "display-only",
  "domain": "display-only",
  "codes": [
    {
      "id": "C-1",
      "name": "Observable failure name",
      "description": "Task-neutral diagnostic definition.",
      "category": "Custom"
    }
  ]
}
```

The store is flat: one JSON file per taxonomy, named `<taxonomy_id>.json`.

## Built-in MAST

If a run starts without inheritance, Finding returns `none` and the runtime resolves that to the built-in MAST constant.

MAST is not a store record and does not appear in the interactive picker.

## Inherit a taxonomy

Non-interactive:

```bash
atlas-single-run --config atlas.json --inherit my-taxonomy-v1 --model gpt-5 --task "..."
```

Interactive picker:

```bash
atlas-find --inherit-pick
```

The picker shows a global table with exactly:

- repo
- taxonomy_id
- domain

Clicking a row opens the full taxonomy content. Choosing “use none / start from 0” returns `none`.

## Register a taxonomy

```bash
atlas-register-taxonomy --file taxonomy.json --id my-taxonomy-v1
```

## Import existing traces

Generate and store an inheritable taxonomy from traces you already have:

```bash
atlas-import-traces \
  --config atlas.json \
  --traces ./traces
```

Imported taxonomies become normal flat store records after acceptance. If you need a specific ID, register a prepared taxonomy with `atlas-register-taxonomy --id ...`.

## Lineage

Generated and refined taxonomies get new taxonomy IDs. Refinement records lineage from the previous taxonomy to the accepted replacement so future runs can preserve the evolution history.
