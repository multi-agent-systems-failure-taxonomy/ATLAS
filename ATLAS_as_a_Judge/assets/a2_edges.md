You are ATLAS-as-a-Judge drawing the CAUSAL edges between already-identified failure points.

The trace is pre-split into numbered UNITS. A previous pass identified the FAILURE POINTS (nodes) below, each anchored to a unit. Your job: return the directed cause -> effect edges between them.

$guide

## Failure points (nodes)
$nodes

## Output
Return ONLY this JSON object, nothing else:
{
  "edges": [
    { "cause": 0, "effect": 1, "rationale": "one sentence: how A's fault triggered B's fault" }
  ]
}

- "cause" and "effect" are the integer NODE ids from the [NODE n] tags.
- cause must come before effect (smaller unit).
- Include an edge ONLY when the test in the guide holds.
- If nothing is causally connected, return {"edges": []}.

## Task the agent was solving
$task

## Units (the trace)
$units
