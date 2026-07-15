ATLAS runtime interaction is active for this Codex session.

Do not dump the active taxonomy into the task context at startup. When a Codex
hook asks for an ATLAS reflection, follow the hook prompt exactly:

1. Observe concrete recent activity.
2. Correlate only evidence-supported causes.
3. Map supported failures to taxonomy codes, or write `none apply`.
4. Decide whether one focused repair is needed.

Before declaring the task complete, perform the final ATLAS check internally.
`none apply` is valid; do not invent a failure mode or force an unnecessary
edit. End every substantive final answer with this compact, user-visible block:

Checkpoint: <what was completed or why the task is unresolved>
Relevant codes: <active taxonomy ids, or none apply>
Evidence: <concrete verification or trajectory evidence>
Next action: <complete or continue when ready; repair or report unresolved otherwise>

The Codex Stop hook captures that block in one callback. Do not wait for a
second Stop prompt and do not expose a long private reflection.

When additional runtime context announces a native taxonomy learning job,
spawn the supplied Codex subagent task once and continue normal work in parallel.
