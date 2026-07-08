# Runtime API and custom harnesses

ATLAS is designed so harnesses can integrate without reimplementing taxonomy finding, trace persistence, or learning thresholds.

## Runtime contract

A harness should:

1. start an ATLAS session when a task starts;
2. pass a mandatory trace output or config containing `trace_output`;
3. let Finding resolve the active taxonomy;
4. invoke checkpoint or advisory gates at meaningful boundaries;
5. invoke the final gate before completion;
6. record one canonical trace at session end.

## Taxonomy selection contract

Finding returns:

- a concrete `taxonomy_id` when `--inherit <taxonomy_id>` is supplied;
- `none` when there is no inherited taxonomy or the interactive picker chooses start-from-zero.

The runtime maps `none` to built-in MAST. Finding itself does not load MAST as a store record.

## Public commands for harnesses

| Command | Use |
|---|---|
| `atlas-find` | Taxonomy selection and interactive picker. |
| `atlas-dashboard` | Dashboard process. |
| `atlas-traces` | Trace status and inspection. |
| `atlas-register-taxonomy` | Store a completed taxonomy record. |
| `atlas-import-traces` | Build a taxonomy from existing trace files. |
| `atlas-doctor` | Validate paths, config, and optional dependencies. |

## What should stay harness-specific

Each harness owns:

- how it represents events;
- how it extracts tool/subagent output;
- which boundaries are meaningful enough to call ATLAS;
- how it displays blocking messages to the agent.

ATLAS owns:

- taxonomy selection;
- final-gate protocol validation;
- trace persistence;
- dashboard state;
- generation/refinement trigger timing;
- taxonomy storage.

See [INTEGRATION.md](../INTEGRATION.md) for a broader pipeline integration guide.
