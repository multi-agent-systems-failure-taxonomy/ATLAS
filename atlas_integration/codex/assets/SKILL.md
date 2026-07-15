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
- When the SessionStart context says taxonomy selection is pending, show the
  supplied selector verbatim and do no task work until the user chooses. After
  selection, resume any held task without asking the user to repeat it.
- When the selector reports `No taxonomy`, do not emit ATLAS checkpoints or
  describe ATLAS as active for that conversation.
- Before final submission, complete a final ATLAS gate and only report ready when no unresolved taxonomy-relevant issue remains.
- When runtime context announces an `ATLAS native taxonomy learning` job,
  immediately launch exactly one native Codex subagent with the supplied task
  prompt. Continue the user's main work while it runs. Do not perform the
  taxonomy job in the main agent, invoke `codex exec`, request an API key, or
  recursively launch another taxonomy agent. The subagent must return the
  supplied receipt envelope exactly; ATLAS validates and activates it.
- End each substantive Codex final answer with the compact checkpoint required
  by the active runtime context: `Checkpoint`, `Relevant codes`, `Evidence`,
  and `Next action`. Keep the longer Observe/Correlate/Map/Decide reflection
  internal unless a hook explicitly requests it.

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
