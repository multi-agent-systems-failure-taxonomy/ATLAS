# ATLAS Claude Code integration

Claude Code runtime skin. It delivers the active taxonomy only at reflection
gates, records live firing evidence, and captures one canonical learning trace
when the Claude session ends. Taxonomy generation, refinement, and storage
remain engine-owned and are invoked through the public lifecycle API.

Install the package, then install project-local hooks:

```powershell
atlas-claude-install `
  --project-dir C:\path\to\project `
  --trace-output C:\path\to\program-traces `
  --trace-root C:\path\to\learning-traces `
  --atlas-model gpt-5.4
```

Registrations invoke the installed module rather than a source-checkout file.
Uninstall with:

```powershell
atlas-claude-uninstall --project-dir C:\path\to\project
```

When upgrading from the old global `atlas-failure-modes` hooks, add
`--migrate-legacy-global` to either command. Unrelated Claude settings are
preserved.

The installer verifies the locally installed Claude Code binary before writing
`.claude/settings.local.json`. Verified events:

- `SessionStart`: select and hold the session taxonomy; inject only standing
  checkpoint instructions.
- `SessionEnd`: idempotent fallback capture for interrupted sessions that did
  not finish through the Stop gate.
- `TaskCompleted`: blocking sub-task checkpoint.
- `SubagentStop`: blocking subagent checkpoint.
- `Stop`: blocking full submission gate.
- `PostToolUse`: nonblocking nudge when a nominally successful tool response
  contains a failure signature.
- `PostToolUseFailure`: nonblocking nudge for actual tool execution failures.

Taxonomy content is surfaced only when a checkpoint fires. Accepted reflections
write taxonomy-version-scoped runtime evidence to
`<trace-output>/.atlas-runtime-evidence.json`; the live dashboard overlays it
without changing the taxonomy record.

Observed on Claude Code 2.1.181: `TaskCompleted` applies to explicit Claude
task objects. A main task that creates no task object is still covered by
`Stop`, but that version does not emit `TaskCompleted` for the main task.

On a successful Stop release (including bounded retry-guard release), the
adapter records the complete Claude JSONL transcript as one `GenerationTrace`
and calls `atlas_runtime.record_trace()` followed by `end_session()`. The
`SessionEnd` hook performs the same operation only when Stop did not already
capture the session. This lets the existing engine trigger generation or
refinement at its configured thresholds without duplicating learning logic in
the harness.

Claude discovery checks `CLAUDE_CODE_EXECUTABLE`, `claude` on `PATH`, and
common Windows, macOS, and Linux locations. The discovered installation must
contain every required event and blocking/additional-context contract.

For subprocess-based learning backends, `--openai-base-url` may be persisted.
Use `--openai-api-key-env NAME` to persist only the name of an inherited
environment variable; credential values are never written to disk.

Lifecycle controls exposed by the installer include generation threshold and
blocking, taxonomy checking, initial/standard refinement thresholds,
refinement blocking, advanced refinement, and failure-nudge throttling. Run
`atlas-claude-install --help` for the exact options. `--no-dashboard`
persistently suppresses integration-managed dashboards when an outer harness
owns the dashboard.
