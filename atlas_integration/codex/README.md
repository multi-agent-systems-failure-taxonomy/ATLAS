# atlas_integration/codex/

Project-local Codex hook integration for ATLAS.

Codex exposes lifecycle command hooks through `.codex/hooks.json`, so this
adapter registers ATLAS at the Codex hook layer rather than relying only on a
passive skill. The optional skill package is still useful as reusable guidance,
but the main integration is hook-based.

Each Stop callback commits one episode trace from the current user turn, agent
work, tool activity, repairs, and compact final checkpoint since the previous
Stop. Codex Desktop builds do not all redeliver Stop after a hook continuation,
so this adapter intentionally uses one callback rather than depending on a
second reflection-only turn. Follow-up requests in the same Codex conversation
therefore become distinct traces while the conversation follows one taxonomy
lineage.

The stored Codex trajectory is normalized JSONL. Human and assistant messages
plus tool calls/results are retained; developer/system context, reasoning,
hook prompts, installed-skill text, and token accounting are excluded. An
interrupted episode is closed on resume or the next substantive user prompt.

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

For user-level hooks that apply to every Codex project, use automatic project
scope. In this mode `trace_output` is the Atlas interactive-data base rather
than one program directory:

```json
{
  "trace_output": "~/.atlas-skill/interactive",
  "atlas_model": "gpt-5",
  "codex": {
    "project_scope": "auto",
    "task_group": "default",
    "session_selector": "prompt",
    "learning_backend": "codex_subagent"
  }
}
```

Each event resolves to
`<trace_output>/projects/<project-key>/groups/<task-group>/program`. Git
subdirectories share the canonical Git root. Non-Git workspaces use their
resolved working directory. Set `codex.project_id` to intentionally share an
identity across worktrees or paths.

The selector shows the resolved project path. If tools explicitly run under a
different `cwd` or `workdir`, Stop still commits the trace but emits a visible
scope-mismatch warning; the runtime never silently moves an active conversation
between project programs.

With `session_selector` set to `prompt`, a new Codex conversation receives a
compact in-chat taxonomy selector. The first substantive user request is held
until the user replies with a number, taxonomy name, `MAST`, or `No taxonomy`.
After selection, Codex resumes the held request automatically. The selector
exchange is not used as the episode task label.

For an unbound project, MAST is recommended and stored taxonomies are listed.
Choosing a stored taxonomy establishes it as the shared taxonomy for the
project task group. Once bound, later conversations see that taxonomy as the
recommended compatible choice. `No taxonomy` disables ATLAS gates and trace
capture for only that conversation.

`learning_backend: "codex_subagent"` uses a detached, authenticated
`codex exec` worker and does not require an external API key. The worker reads
an immutable outcome-blind snapshot and submits a staged candidate. Hook
reconciliation owns validation and project-local activation. Generation and
refinement trigger notices appear immediately; completion appears once on the
triggering conversation's next hook event because command hooks cannot push a
message into an idle Codex task.

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
| `SessionStart` | Start/load ATLAS or initialize the conversation selector. |
| `UserPromptSubmit` | Hold the first task, resolve the choice, and start the selected episode. |
| `Stop` | Single-pass compact final checkpoint and episode commit. |
| `SubagentStop` | Observational, non-blocking compact checkpoint capture. |
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
| [`transcript.py`](transcript.py) | Codex-specific transcript normalization, filtering, bounds, and project-workdir detection. |
| [`install.py`](install.py) | Writes `.codex/hooks.json`, `.codex/atlas-skill.json`, and optional skill files. |
| [`uninstall.py`](uninstall.py) | Removes ATLAS hook registrations and optional skill files. |
| [`state.py`](state.py) | Per-session Codex hook state under the program trace output. |
