# Claude Code integration

The Claude Code integration installs hooks that call the ATLAS runtime at
session start, user-prompt submission, checkpoints, and final submission. It
supports both project-local operation and a user-level interactive mode shared
with Codex.

## Install for every Claude Code conversation

```powershell
atlas-claude-install `
  --user-level `
  --trace-output "$HOME\.atlas-skill\interactive" `
  --trace-root "$HOME\.atlas-skill\traces" `
  --atlas-model claude-session `
  --project-scope auto `
  --task-group default `
  --session-selector prompt `
  --learning-backend claude_subagent
```

This merges ATLAS into `~/.claude/settings.json` and writes
`~/.claude/atlas-skill.json`; unrelated settings and plugins are preserved.
Claude and Codex resolve the same project/task-group program when their base
`trace_output`, project root, and task group match.

No external model API key is required for `claude_subagent`. The worker invokes
the authenticated local `claude -p` automation surface with safe mode, tools
disabled, no session persistence, and a strict JSON schema. It receives a
frozen outcome-blind trace snapshot and writes only a proposal receipt. A
foreground hook validates evidence and activates between episodes.

One completed assistant episode is one trace. Generation starts after five
eligible traces by default, first refinement review after `k_init` (ten), and
later reviews every `k` traces (twenty). MAST or the current learned taxonomy
remains active while the worker runs. Trigger and completion notices appear in
Claude's visible `systemMessage` and agent-facing `additionalContext`.

Remove only the user-level ATLAS registration with:

```powershell
atlas-claude-uninstall --user-level
```

## Install hooks

```bash
atlas-claude-install --project-dir . --config atlas.json
```

Then start Claude Code in that project.

ATLAS will:

1. ask for MAST, a compatible stored taxonomy, or `No taxonomy` when enabled;
2. hold the first substantive prompt until that choice is resolved;
3. fire checkpoint reflections at configured boundaries;
4. block final completion until the final gate passes or exhausts the retry envelope;
5. record one canonical episode trace at each accepted Stop boundary;
6. trigger durable generation or refinement jobs when thresholds are reached.

If a detached worker disappears without a receipt, the coordinator expires its
lease, keeps the current taxonomy active, and permits a retry from the same
frozen evidence. Automatic secret redaction before trace persistence remains a
production hardening item; do not place credentials in task transcripts.

## Customize built-in hooks

Examples:

```bash
# Disable the built-in subagent checkpoint.
atlas-claude-install --project-dir . --config atlas.json --disable-hook SubagentStop

# Only run post-tool advisory nudges after selected tools.
atlas-claude-install --project-dir . --config atlas.json --post-tool-use-matchers Bash,Edit,Write
```

You can also configure built-in hooks in `atlas.json`:

```json
{
  "claude_code": {
    "built_in_hooks": {
      "SubagentStop": false,
      "PostToolUse": {
        "enabled": true,
        "matchers": ["Bash", "Edit", "Write"]
      },
      "PostToolUseFailure": ["Bash"]
    }
  }
}
```

## Add custom hooks

Custom hooks are useful when you want ATLAS to fire on a specific event or tool rather than every possible boundary.

```bash
atlas-claude-add-hook \
  --project-dir . \
  --name pre-bash \
  --event PreToolUse \
  --matcher Bash \
  --command-pattern "python .*eval" \
  --checkpoint-key fixed \
  --mode blocking
```

List hooks:

```bash
atlas-claude-list-hooks --project-dir .
```

Remove one hook:

```bash
atlas-claude-remove-hook --project-dir . --name pre-bash
```

Use `blocking` when the agent must satisfy the reflection contract before continuing. Use `advisory` when ATLAS should nudge but not block.

`--command-pattern` narrows a broad tool matcher, for example `Bash`, to one
recurring command. `--checkpoint-key fixed` is useful for recurring gates that
should open one checkpoint and close it on the next matching event.

## Gates fail open

If an ATLAS hook itself crashes or is killed at Claude Code's per-hook
timeout, the agent continues normally and that gate silently does not fire.
This is deliberate: an ATLAS bug must never leave your session unable to
finish. The trade-off is that a skipped gate is quiet — when gating matters
(A/B runs, benchmarks), verify it happened rather than assuming:

- `[atlas]` lines on stderr report retry-guard releases and internal errors;
- `<trace_output>/decisions.log` records every gate decision and release;
- `atlas-status --config atlas.json` shows reflections recorded per session —
  a finished session with no final-gate evidence means the gate was skipped.

## Uninstall hooks

```bash
atlas-claude-uninstall --project-dir .
```

This removes ATLAS hook config from the project. It does not delete learned taxonomies or trace folders.

## More implementation detail

See [atlas_integration/claude_code/README.md](https://github.com/multi-agent-systems-failure-taxonomy/ATLAS/blob/main/atlas_integration/claude_code/README.md) for the adapter file map.
