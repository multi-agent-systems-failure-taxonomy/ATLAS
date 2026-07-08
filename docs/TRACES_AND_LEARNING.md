# Traces and learning lifecycle

ATLAS separates runtime interaction from taxonomy learning.

Runtime gates help the current task avoid repeated mistakes. Learning uses completed traces to generate or refine taxonomies for future tasks.

## Trace output is mandatory

Every run needs a trace output. This gives ATLAS a stable folder for the task or program even before a generated taxonomy exists.

For example:

```json
{
  "trace_output": "./atlas-program"
}
```

## Default MAST warm-up

When no taxonomy is inherited, ATLAS starts with built-in MAST.

After `generation_threshold` traces accumulate, ATLAS can start taxonomy generation. The default threshold is `5`.

```json
{
  "generation_threshold": 5,
  "generation_stops": false
}
```

If `generation_stops` is `false`, already-running tasks continue with MAST while generation happens. The generated taxonomy activates only after running tasks finish.

If `generation_stops` is `true`, the task waits until generation finishes.

## Accepted vs rejected generation

Generated taxonomies must pass the configured taxonomy check unless `skip_judge` is enabled.

If the generated taxonomy is rejected or generation fails, warm-up traces stay in the program folder. They are not moved into a taxonomy trace folder until a valid taxonomy is accepted.

After rejection, ATLAS waits until enough new traces have accumulated relative to the rejected snapshot, then generation can run again over the accumulated traces.

## Refinement counters

Once a real stored taxonomy is active, each program tracks its own refinement counter.

Defaults:

```json
{
  "k_init": 10,
  "k": 20,
  "refinement_stops": false
}
```

- `k_init`: traces required before the first refinement for that program and taxonomy.
- `k`: traces required after each later refinement.

If a taxonomy is refined, the accepted candidate gets a new `taxonomy_id`. The publishing program counter resets. Other programs preserve their independent counters.

## Advanced refinement

```json
{
  "advanced_refinement": false
}
```

Standard refinement proposes a refined taxonomy and records a structural diff.

Advanced refinement adds one support-judge repair pass. If issues are found, the refinement model gets the judge output and proposes one repaired taxonomy. The repaired taxonomy is accepted automatically after that single repair pass.

## Trace retention

ATLAS keeps accumulated traces by default. If you run many long tasks, trace folders can grow large.

Current practical recommendation: keep trace roots outside the repository and periodically archive or prune old program folders that are no longer needed for learning.
