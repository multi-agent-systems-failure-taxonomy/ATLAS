# Native taxonomy learning

Codex and Claude Code can generate and refine taxonomies through a subagent in
the active host conversation. No external model API key, standalone host CLI,
or second login is required.

## What triggers learning

Every successful lifecycle hook reconciles existing jobs and checks the
project/task-group thresholds:

| Stage | Default threshold |
|---|---:|
| First taxonomy generation | 5 eligible episode traces |
| First refinement review | 10 traces after activation |
| Later refinement reviews | Every 20 new traces |

Polling is idempotent. If a Stop or SessionEnd event persisted a trace but the
original trigger was interrupted, the next hook repairs the missed trigger.

## Job lifecycle

```text
queued -> claimed -> awaiting_reconcile -> activating
       -> activated | no_change
       -> rejected | failed
```

1. ATLAS freezes the exact trace references and source taxonomy version.
2. A `SessionStart` or `UserPromptSubmit` hook claims the job with a time-bound
   token.
3. The main host agent launches exactly one taxonomy subagent and continues the
   user's task.
4. The subagent reads `prompt.txt` and `output.schema.json`, then returns one
   bounded receipt through `SubagentStop`.
5. Foreground reconciliation validates the claim, snapshot hash, trace
   evidence, candidate structure, lineage, and idle activation boundary.
6. A valid candidate is registered and activated atomically. Failure leaves
   MAST or the current taxonomy active.

## Worker boundary

The taxonomy subagent may read only its frozen prompt and schema. It must not:

- browse the repository or network;
- inspect credentials;
- edit files or activate a taxonomy;
- invoke `codex exec`, `claude -p`, or another taxonomy agent;
- perform the user's main task.

Candidate codes must cite supporting frozen trace IDs and include a rationale.
That evidence is retained for validation and audit. The runtime-facing code
definition remains its ID, name, description, and category.

## Visible notices

The originating conversation receives exactly-once notices when generation or
refinement is triggered and when it finishes. A finish notice may appear on
the next lifecycle event if the host cannot inject output into an idle
conversation.

## Recovery

- An expired claim returns to the queue for a later task.
- A duplicate hook cannot queue a second active job for the same group.
- A stale refinement candidate is rejected when its parent taxonomy changed.
- A malformed receipt is ignored and reported; it cannot update the store.
- Legacy detached-worker jobs are retired before the native path queues a
  replacement from the persisted evidence.

Use `atlas-status` to inspect the active taxonomy, trace counts, and learning
state. See [Troubleshooting](TROUBLESHOOTING.md) when a job remains queued.
