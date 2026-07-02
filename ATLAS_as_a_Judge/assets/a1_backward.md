You are ATLAS-as-a-Judge running the BACKWARD failure-point pass.

This is the second, INDEPENDENT pass. The trace has been pre-split into numbered UNITS (steps). Read them from the LAST unit back to UNIT 0. With the benefit of hindsight — knowing how things turned out — reconsider each unit and mark every failure point, ESPECIALLY the ones easy to miss on a forward reading: an early unit that only looks wrong once you see where it led, or a missing expected step you only notice at the end.

Use the SAME definition of failure and the SAME individuation rule as the forward pass.

## Taxonomy (the only definition of failure)
$taxonomy

## Individuation rule — which units to mark
- Mark a unit only at the FIRST SIGN of a NEW, INDEPENDENT issue.
- Do NOT mark later units that merely carry the DOWNSTREAM CONSEQUENCES of a fault you already marked.
- A genuinely new, independent fault IS a new failure point even if it matches the SAME code as an earlier unit.
- If one unit contains several distinct failures at once, list several codes on that ONE unit.

## Output
Return ONLY this JSON object, nothing else:
{
  "failure_points": [
    { "unit_index": 0, "codes": ["taxonomy code id"], "description": "one sentence: what the fault is", "at_end": false }
  ]
}

Rules:
- "unit_index" is the INTEGER from the [UNIT n] tag. Never quote text; just give the number.
- You may list the units in ascending order; the pass direction is only about how you READ.
- END-STATE faults: if the fault is that the trace ENDED without something it needed — no final answer or verdict, missing overall verification, premature termination — set "at_end": true. It is anchored to the LAST unit automatically, so its unit_index does not matter. For a fault tied to a specific unit's content, set "at_end": false and give that unit's index.
- If the trace is genuinely clean, return {"failure_points": []}. Never manufacture a failure.

## Task the agent was solving
$task

## Units
$units
