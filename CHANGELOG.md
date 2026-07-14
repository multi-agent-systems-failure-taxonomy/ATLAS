# Changelog

All notable user-facing changes are documented here.

## Unreleased

### Fixed

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
