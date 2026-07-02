You are judging whether an agent SOLVED its task. Use the failure-mode analysis below as EVIDENCE, not as a verdict.

A prior analysis detected failure points in the agent's trace and how they causally connect (the graph below). IMPORTANT: a failure graph does NOT automatically mean the task failed. Failures can be recovered from, and some are minor or non-terminal. Weigh whether the detected failures actually PREVENTED success, given the agent's final result.

## Task
$task

## Detected failure graph (evidence — not a verdict)
$graph

## Agent trace
$trace

## How to decide
- Look at the agent's FINAL result (its final output / answer / patch) and whether it actually accomplishes what the task asked.
- A failure cascade matters only if it is TERMINAL — unrecovered and reaching the final result. A cascade the agent later recovered from does not sink the task.
- A trace with no failure points is not automatically correct, and a trace with many is not automatically incorrect.
- Nodes marked CROSS-EXAMINATION are different from process failures: they mean independent solutions to this same task AGREE on a behavior, location, or scope that this agent's final solution lacks or contradicts. That is artifact-level evidence of incorrectness — it cannot have been "recovered from", because it is about the final result itself. Weigh such nodes HEAVILY toward "incorrect"; discount one only if the description shows a mere style/approach difference with clearly equivalent behavior. Do not override consensus evidence just because the agent's solution looks plausible to you — plausible-but-wrong is the exact failure mode cross-examination exists to catch.

## Output
Return ONLY this JSON object, nothing else:
{
  "verdict": "correct",
  "confidence": 0.0,
  "failure_codes": ["codes most responsible, if incorrect"],
  "evidence": ["short observation", "..."]
}

- "verdict": "correct" if the agent solved the task, otherwise "incorrect".
- "confidence": your confidence in that verdict, between 0 and 1.
- "failure_codes": the taxonomy codes most responsible for a failure (empty if correct).
