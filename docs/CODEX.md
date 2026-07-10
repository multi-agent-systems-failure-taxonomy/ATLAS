# Codex integration

The Codex integration installs project-local hooks that call ATLAS from Codex session and boundary events.

## Install hooks

```bash
atlas-codex-install --project-dir . --config atlas.json
```

This writes:

- `.codex/hooks.json`
- `.codex/atlas-skill.json`

Open `/hooks` inside Codex and trust the ATLAS hooks before relying on them.

## Default events

The default Codex setup uses:

1. `SessionStart`: deliver standing ATLAS context.
2. `Stop`: block final completion until the ATLAS final gate passes.
3. `SubagentStop`: checkpoint subagent trajectories.
4. `PostToolUse`: add advisory nudges after selected failed tool outputs.

## Optional skill guidance

```bash
atlas-codex-install --project-dir . --config atlas.json --install-skill
```

This copies the ATLAS guidance skill into the project-local Codex config so the agent has the same natural-language protocol as the hook adapter.

## Custom hook policy

Use `codex.hooks` in `atlas.json` when you want ATLAS to trigger only on selected Codex events:

```json
{
  "codex": {
    "hooks": {
      "SessionStart": true,
      "Stop": true,
      "SubagentStop": true,
      "PostToolUse": {
        "enabled": true,
        "matchers": ["shell_command", "apply_patch"]
      }
    }
  }
}
```

Keep strict final gates on `Stop`; use advisory hooks for noisier events.

## Uninstall hooks

```bash
atlas-codex-uninstall --project-dir .
```

This removes ATLAS hook config from the project. It does not delete learned taxonomies or trace folders.

## More implementation detail

See [atlas_integration/codex/README.md](https://github.com/multi-agent-systems-failure-taxonomy/ATLAS/blob/ATLAS_SKILL/atlas_integration/codex/README.md) for the adapter file map.
