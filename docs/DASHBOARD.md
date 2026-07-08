# Dashboard

ATLAS includes a read-only localhost dashboard for watching taxonomy codes fire during runs.

## Open manually

```bash
atlas-dashboard \
  --trace-output ./atlas-program \
  --store-dir ~/.atlas-skill/taxonomies
```

Integrations can also launch it automatically when `dashboard` is true in `atlas.json`.

## What it shows

The dashboard is organized around recorded trace evidence:

- active taxonomy metadata;
- task IDs and task UIDs;
- failure-mode codes that fired;
- evidence snippets and reasoning captured by the gate;
- learning state when generation or refinement is pending.

## UID filtering

Use the search bar at the top to filter to a single task UID, such as `UID0118`.

If `A.2`, `A.5`, and `C.1` fired for `UID0118`, searching that UID hides unrelated tasks and shows only the matching `UID0118` entries and their associated codes.

This is useful when several tasks share the same dashboard and multiple failure modes fire across different tasks.

## Local-only behavior

The dashboard binds to localhost by default and is intended as a development/runtime inspection tool. It should not be exposed publicly without an external authentication layer.
