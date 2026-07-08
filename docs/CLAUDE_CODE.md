# Claude Code integration

The Claude Code integration installs project-local hooks that call the ATLAS runtime at session start, checkpoints, and final submission.

## Install hooks

```bash
atlas-claude-install --project-dir . --config atlas.json
```

Then start Claude Code in that project.

ATLAS will:

1. resolve an inherited taxonomy if configured, otherwise use built-in MAST;
2. deliver standing ATLAS context at session start;
3. fire checkpoint reflections at configured boundaries;
4. block final completion until the final gate passes or exhausts the retry envelope;
5. record a canonical trace at session end;
6. trigger taxonomy generation or refinement when thresholds are reached.

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

## Uninstall hooks

```bash
atlas-claude-uninstall --project-dir .
```

This removes ATLAS hook config from the project. It does not delete learned taxonomies or trace folders.

## More implementation detail

See [atlas_integration/claude_code/README.md](../atlas_integration/claude_code/README.md) for the adapter file map.
