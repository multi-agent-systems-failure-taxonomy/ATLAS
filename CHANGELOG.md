# Changelog

All notable user-facing changes are documented here.

## 1.1.0b1 - Unreleased

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
