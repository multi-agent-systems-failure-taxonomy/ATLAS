# atlas_integration/codex/

Project-local Codex hook integration for ATLAS.

Codex exposes lifecycle command hooks through `.codex/hooks.json`, so this
adapter registers ATLAS at the Codex hook layer rather than relying only on a
passive skill. The optional skill package is still useful as reusable guidance,
but the main integration is hook-based.

## Install hooks

```bash
atlas-codex-install \
  --project-dir /path/to/project \
  --trace-output /path/to/atlas-program \
  --atlas-model gpt-5
```

Or with a shared `atlas.json`:

```bash
atlas-codex-install --project-dir . --config atlas.json
```

The installer writes:

```text
<project>/.codex/hooks.json
<project>/.codex/atlas-skill.json
```

After install, open `/hooks` in Codex and trust the ATLAS hooks. Codex records
trust against the hook definition hash, so changed hooks need review again.

## Default hook events

| Event | ATLAS behavior |
|---|---|
| `SessionStart` | Start/load the ATLAS session and deliver standing context. |
| `Stop` | Blocking final submission gate. |
| `SubagentStop` | Blocking checkpoint reflection for subagent completion. |
| `PostToolUse` | Advisory failure nudge after selected failed tool outputs. |

Defaults can be customized:

```bash
atlas-codex-install \
  --project-dir . \
  --config atlas.json \
  --disable-hook SubagentStop \
  --post-tool-use-matchers Bash,Edit,Write
```

The config-file equivalent is top-level `codex_hooks`:

```json
{
  "codex_hooks": {
    "SubagentStop": false,
    "PostToolUse": {
      "enabled": true,
      "matchers": ["Bash", "Edit|Write"]
    }
  }
}
```

## Optional Codex skill

To also install the reusable Codex skill guidance:

```bash
atlas-codex-install --project-dir . --config atlas.json --install-skill
```

By default this writes `atlas-failure-modes` under `$CODEX_HOME/skills` if
`CODEX_HOME` is set, otherwise under `~/.codex/skills`.

## Uninstall

```bash
atlas-codex-uninstall --project-dir .
```

This removes only ATLAS hook registrations from `.codex/hooks.json` and deletes
`.codex/atlas-skill.json`. To also remove the optional skill files:

```bash
atlas-codex-uninstall --project-dir . --remove-skill
```

## Programs

| File | Purpose |
|---|---|
| [`config.py`](config.py) | `CodexConfig` and hook-event configuration. |
| [`dispatcher.py`](dispatcher.py) | Command hook entry point; reads Codex hook JSON from stdin and emits JSON back to Codex. |
| [`runtime.py`](runtime.py) | SessionStart, Stop, SubagentStop, and PostToolUse behavior on top of `atlas_runtime`. |
| [`install.py`](install.py) | Writes `.codex/hooks.json`, `.codex/atlas-skill.json`, and optional skill files. |
| [`uninstall.py`](uninstall.py) | Removes ATLAS hook registrations and optional skill files. |
| [`state.py`](state.py) | Per-session Codex hook state under the program trace output. |
