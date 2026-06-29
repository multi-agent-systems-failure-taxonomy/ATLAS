---
name: atlas-failure-modes
description: Use when working on an agent task where ATLAS failure-mode checkpoints, final submission gates, trace capture, taxonomy generation/refinement, or ATLAS CLI setup should guide Codex. This skill helps Codex apply ATLAS during software or research tasks, diagnose its own trajectory against the active taxonomy, and avoid claiming completion before the ATLAS final gate is satisfied.
---

# ATLAS for Codex

Use ATLAS as a lightweight runtime discipline while doing the user's task.

## Runtime behavior

- Keep the active taxonomy out of startup context unless the user or an ATLAS command explicitly supplies it.
- At meaningful boundaries, inspect the recent trajectory before continuing:
  - finishing a sub-task;
  - recovering from a failed tool command;
  - switching strategy;
  - preparing to submit a final answer.
- Use the reflection order from ATLAS prompts:
  1. Observe concrete events or missing expected steps.
  2. Correlate only evidence-supported causes.
  3. Map to taxonomy codes only when evidence supports the match.
  4. Decide whether to make one focused repair or continue.
- Treat `none apply` as valid. Do not invent a failure mode or force an edit.
- Before final submission, complete a final ATLAS gate and only report ready when no unresolved taxonomy-relevant issue remains.

## If the ATLAS package is available

Prefer the package CLIs over hand-rolled state:

- Use `atlas-doctor --config atlas.json` to check setup.
- Use `atlas-find --list` or `atlas-find --inherit <taxonomy_id>` to resolve stored taxonomies.
- Use `atlas-single-run` for no-harness single-model tasks.
- Use `atlas-dashboard` to inspect recorded evidence and fired codes.
- Use `atlas-traces status` to inspect trace growth.

If a command asks for `--trace-output`, use the project-specific trace folder supplied by the user or `./atlas-program` for local experiments.

## If no ATLAS command is available

Still follow the ATLAS final-gate shape in the final reasoning pass:

- `Final ATLAS status:` `READY_TO_SUBMIT` or `REPAIR_REQUIRED`
- `Codes checked:` relevant taxonomy ids, or none
- `Evidence:` concrete task or verification evidence
- `Repair attempts used:` integer count
- `Final decision:` submit, repair, or report unresolved

Do not expose private chain-of-thought. Keep the final user-facing answer concise; mention only the actionable result and verification status.
