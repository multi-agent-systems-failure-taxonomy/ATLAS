# Changelog

All notable user-facing changes are documented here.

## Unreleased

## 1.1.0b4 - 2026-07-15

### Fixed

- Codex no longer opens the taxonomy browser from a new `SessionStart` event.
  The picker opens on the first real `UserPromptSubmit`, so background host
  tasks and spawned agent sessions cannot create unsolicited browser windows.
- Native learning polling and job claims now require an active taxonomy
  selection when the conversation selector is enabled. Internal sessions no
  longer receive recursive taxonomy-generation directives.
- Resuming a selected Codex conversation remains silent and preserves its
  existing taxonomy; resuming an unselected pending conversation waits for the
  next user prompt instead of reopening the browser immediately.
- Detached taxonomy pickers now tolerate slow Windows interpreter startup and
  terminate their worker if readiness still fails, instead of leaving an
  orphaned localhost process.

## 1.1.0b3 - 2026-07-15

### Added

- Codex-native taxonomy learning now uses a subagent in the active task with a
  durable claim/receipt protocol. It no longer requires a standalone Codex CLI
  login or an external model API key.
- Every Codex lifecycle hook polls generation and refinement progress,
  idempotently repairing a missed threshold trigger on the next event.
- Codex conversations can select MAST in a project that already has a learned
  taxonomy. The selection creates a durable isolated `fresh-*` task group and
  preserves the project's shared default taxonomy.
- Codex conversations open a session-bound localhost taxonomy library directly
  from `SessionStart`. The browser applies and persists the choice before
  reporting success, without depending on a later `UserPromptSubmit` event.
- The taxonomy library now uses the ATLAS runtime visual language, provides a
  searchable taxonomy rail and full code inspection, and treats generated
  evidence as secondary expandable provenance.
- Claude Code taxonomy learning now uses native Agent subtasks in the active
  session with the same durable claim/receipt lifecycle as Codex. It no longer
  requires a standalone `claude -p` login or external model API key.
- Claude Code now supports the session-bound browser library, direct taxonomy
  activation, durable fresh-MAST conversation routes, and missed-threshold
  polling on every successful lifecycle hook.
- The documentation site now leads with host installation, native-learning
  behavior, architecture ownership, and a complete local dashboard example.

### Changed

- Codex taxonomy workers receive only a frozen prompt and output schema, then
  return a bounded receipt through `SubagentStop`. The foreground hook
  coordinator remains the sole validator and activation owner.
- `codex.worker_model` and `codex.codex_cli_path` remain readable compatibility
  fields but are not used by native in-task learning.
- `claude_code.worker_model` and `claude_code.claude_cli_path` remain readable
  compatibility fields but are not used by native in-session learning.
- Taxonomy selectors and the browser catalog prefer a human-facing
  `display_name` while keeping generated taxonomy IDs as immutable internal
  keys. Older records fall back to their domain, and new native candidates may
  provide a concise display name.
- Host-neutral browser transport, fresh-session routing, threshold polling,
  and receipt validation now live in `atlas_integration/interactive`; Codex and
  Claude Code retain stable facade modules for compatibility.

### Fixed

- Final-gate status parsing now accepts a bounded vocabulary and uses a
  runtime-owned repair counter, preventing negated prose or model-supplied
  attempt counts from bypassing the gate.
- Native taxonomy replacement codes now require exact frozen-trace quotes;
  activation verifies every span and records a per-code validation result.
- Active sessions now carry heartbeat leases, and activation/status paths
  conservatively reconcile abandoned sessions after a legacy grace lease.
- Malformed or unreadable trace files now abort learning snapshots with the
  affected path instead of silently changing the evidence set.
- Codex compact checkpoints recognize `no further action required` as complete.
- Codex and Claude uninstallers now remove exact managed dispatcher commands
  while preserving unrelated hooks with ATLAS-like names or config paths.
- Repository licensing, vendored-pipeline provenance, result-artifact claims,
  package maps, linting, and a 78% coverage floor now match the shipped files.

- Codex user-level hooks now ignore host-maintenance conversations rooted in
  `~/.codex/memories`, preventing internal memory work from opening a taxonomy
  browser alongside an unrelated user task.
- Resumed Codex and Claude Code conversations recover an exact legacy inline
  taxonomy reply from their transcript before launching the browser. This
  repairs selections missed when `UserPromptSubmit` was not emitted.
- Codex and Claude Code context now distinguishes the taxonomy originally
  selected as a lineage seed from the generated or refined taxonomy currently
  active. Checkpoints are explicitly directed to the active taxonomy's codes
  instead of continuing to present MAST as pinned after activation.
- Resumed Codex and Claude Code conversations now retain their original ATLAS
  program scope even when the host reports a different current working
  directory. Existing selected or disabled session state is migrated into the
  new durable conversation-scope binding before a selector can reopen.
- The browser selector confirmation now names the active host instead of
  always telling Claude Code users to return to Codex.
- Codex Desktop sessions that omit `UserPromptSubmit` no longer remain stuck in
  `ATLAS is waiting for taxonomy selection` after a browser choice.
- The Codex selector now displays MAST as a numbered choice even when the
  project already has a learned taxonomy; its reply instructions no longer
  advertise a hidden option.
- Claude taxonomy receipts bypass the ordinary blocking `SubagentStop`
  reflection, preventing the learning Agent from recursively gating itself;
  all other Claude subagents retain the existing checkpoint behavior.

- The user-level interactive placeholder model (`interactive-session`)
  adopts whatever ATLAS model a program already records instead of raising
  a conflict. Program state written by an earlier release (which recorded
  the old default model) no longer fails every hook event in previously
  used projects.

## 1.1.0b2 - 2026-07-14

### Fixed

- Claude Code hooks are registered as `python -m
  atlas_integration.claude_code.dispatcher` instead of an absolute dispatcher
  file path, so switching between wheel and editable installs (or relocating
  the package) no longer breaks every hook event.
- Shared state files (program manifest, session state, worker heartbeats,
  traces, learning jobs, evidence, dashboard state) retry atomic replaces and
  reads on Windows sharing violations instead of failing hooks and background
  learning jobs with transient `PermissionError`.
- Read-only manifest lock cycles (activation polls, cadence checks) no longer
  rewrite the manifest file on every exit.
- Hook dispatchers pin stdin/stdout/stderr to UTF-8, fixing mojibake in gate
  and selector text on Windows hosts.
- Native learning workers scrub the spawning session's transport variables
  (`ANTHROPIC_BASE_URL`, host OAuth plumbing, `OPENAI_BASE_URL`) so the
  detached CLI authenticates with its own persisted login instead of failing
  with 401s against a session-scoped gateway. Deliberate user API keys are
  preserved.

## 1.1.0b1 - 2026-07-14

### Added

- User-level, zero-config Codex and Claude Code installers.
- One completed assistant episode per trace for interactive conversations.
- Automatic Git-project and task-group scoping shared across conversations.
- In-chat taxonomy selection with MAST, compatible stored taxonomies, and an
  ATLAS-off choice.
- Detached native taxonomy generation and refinement workers that reuse the
  signed-in Codex or Claude Code CLI instead of requiring a separate API key.
- Visible, exactly-once generation and refinement trigger/completion notices.
- Durable, idempotent learning jobs with frozen evidence snapshots, stale-job
  recovery, validation before activation, and taxonomy lineage.
- Interactive installation and native-worker diagnostics in `atlas-doctor`.

### Changed

- Codex skill guidance now installs to the documented user skill directory,
  `~/.agents/skills`.
- Codex and Claude Code use a shared interactive learning-state contract while
  retaining host-specific worker launchers.
- Bedrock taxonomy calls honor the configured ATLAS timeout and adaptive retry
  policy.

### Compatibility

- Existing `codex_learning` manifest state migrates to `interactive_learning`
  on first use.
- Project-local, provider-backed installs keep their existing required config
  and defaults.

## 1.0.0

- Initial packaged ATLAS runtime with MAST fallback, trace persistence,
  generation/refinement, dashboard, Claude Code, Codex, single-LLM, and
  harness-neutral integrations.
