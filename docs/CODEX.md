# Codex integration

The Codex integration installs user-level or project-local hooks that call
ATLAS from Codex session and boundary events.

## Install for every Codex conversation

```bash
atlas-codex-install --user-level
atlas-doctor --codex
```

No `atlas.json` or separate model API key is required. The installer writes
`~/.codex/hooks.json`, `~/.codex/atlas-skill.json`, and the guidance skill at
`~/.agents/skills/atlas-failure-modes`.

The defaults are automatic Git-project scoping, task group `default`, the
conversation selector, generation after five traces, and native
`codex_subagent` learning in the active task. Open `/hooks` inside Codex and
trust the installed ATLAS hooks. Native learning uses the task's existing Codex
session, so no separately runnable CLI or second login is required.

## Install project-local hooks

```bash
atlas-codex-install --project-dir . --config atlas.json
```

This writes:

- `.codex/hooks.json`
- `.codex/atlas-skill.json`

Open `/hooks` inside Codex and trust the ATLAS hooks before relying on them.

## Default events

The default Codex setup uses:

1. `SessionStart`: recover standing context for an already selected conversation.
2. `UserPromptSubmit`: open a new conversation's taxonomy library and handle episode boundaries.
3. `Stop`: capture the compact final checkpoint and commit the episode in one callback.
4. `SubagentStop`: capture a compact subagent checkpoint when present without blocking.
5. `PostToolUse`: add advisory nudges after selected failed tool outputs.

## Conversation selector

The user-level command enables the selector automatically. For a project-local
install, configure it explicitly:

```json
{
  "trace_output": "~/.atlas-skill/interactive",
  "atlas_model": "interactive-session",
  "codex": {
    "project_scope": "auto",
    "task_group": "default",
    "session_selector": "prompt",
    "selector_surface": "browser",
    "learning_backend": "codex_subagent"
  }
}
```

A new conversation opens the localhost ATLAS catalog from its first real
`UserPromptSubmit`. Deferring the launch prevents Codex background tasks and
spawned agent sessions from opening selectors during their own startup. The
first substantive request is held while the user chooses. The catalog recommends
MAST for an unbound project and includes compatible stored taxonomies plus `No
taxonomy`. Its `/choose` handler validates the session's allowed options, updates
Codex state, and binds a stored taxonomy to the project/task group before
rendering the activation page. `No taxonomy` disables ATLAS gates and trace
capture only for that conversation.

Catalog and chat surfaces use `display_name` when present and otherwise fall
back to the taxonomy domain. The generated `taxonomy_id` remains visible as
secondary metadata and continues to be the immutable storage and lineage key.

When a project already has a learned taxonomy, the numbered choices are the
learned shared default, `MAST`, and `No taxonomy`. Choosing `MAST` means
"start fresh": ATLAS creates a durable `fresh-<conversation>` task group,
starts that conversation from MAST, and learns a separate taxonomy from zero.
The existing project taxonomy remains the default for every other conversation.

Set `selector_surface` to `"inline"` when opening a local browser is undesirable.
Both surfaces resolve the choice during `UserPromptSubmit`; the browser remains
the default because it provides the complete searchable taxonomy library.

When upgrading an older inline-selector task, `SessionStart` also checks the
transcript after the saved selector boundary. An exact offered reply such as
`MAST` is migrated before the next prompt can open a browser; ordinary task
prose does not match. New selector state is never created at `SessionStart`, so
background host tasks and spawned agents cannot open a browser on startup.

The installer flag is equivalent and overrides `atlas.json` for that install:

```bash
atlas-codex-install --project-dir . --config atlas.json --selector-surface inline
```

The selector includes the resolved project path. Start a task from the actual
repository, or set `codex.project_id`, when the conversational workspace and
the repository being edited differ. Explicit external tool workdirs produce a
scope warning rather than silently rebinding taxonomy state.

## Codex Stop contract

Every substantive final answer ends with the compact fields `Checkpoint`,
`Relevant codes`, `Evidence`, and `Next action`. The Stop hook validates and
captures that block on its first callback. It does not ask Codex for a separate
long reflection because some Codex Desktop builds complete a continuation
without invoking Stop again. A missing block is reported visibly, but the
episode is still closed so project state cannot remain stranded.

Learning traces use normalized Codex JSONL. Developer/system messages,
reasoning payloads, hook prompts, globally installed skill content, and token
events are excluded; human/assistant messages and bounded tool interactions are
retained. Resume and the next user prompt recover unfinished episodes.

## Native taxonomy learning

`codex.learning_backend: "codex_subagent"` runs generation and refinement in
a native subagent of the active Codex task. It does not require a standalone
`codex` executable, separate CLI login, `OPENAI_API_KEY`, or another
user-supplied model credential. The subagent receives a claimed job and may
read only its immutable project/task-group evidence snapshot and output schema.

The fifth eligible episode triggers generation by default. Every lifecycle
hook also polls the durable program. If enough eligible episodes exist but no
job was queued, the next hook repairs the missed trigger idempotently. MAST
remains active while the subagent produces a proposal. The subagent cannot
publish a taxonomy: it returns a bounded receipt in its final message, which
`SubagentStop` passes to the normal hook coordinator for validation and
activation only when no episode is active. The first refinement
review occurs after 10 new episodes and later reviews every 20; a review may
retain the current taxonomy when the evidence does not justify a change.

After activation, Codex context names the active learned taxonomy by display
name and immutable ID. The original selector choice, including MAST, remains
recorded only as the lineage seed; it does not remain the checkpoint vocabulary.

The native worker candidate schema accepts 1 through 30 replacement codes.
Thirty is a safety cap, not a target, so a small five-trace generation snapshot
may produce fewer codes. Every proposed code must cite one or more frozen trace
IDs, include an exact quote from every cited trace, and explain the support.
ATLAS checks the quotes against the immutable snapshot and stores the validation
record inline for audit. A refinement that chooses `no_change` returns no codes;
the coordinator retains the current taxonomy verbatim.

The trigger notice appears in the hook event that queues the worker. Codex
hooks cannot inject into an idle task asynchronously, so the finished notice
appears exactly once on the conversation's next lifecycle event. A failed or
stale result leaves MAST or the current taxonomy active and preserves traces.

`codex.worker_timeout_seconds` controls the native claim lease. The legacy
`codex.worker_model` and `codex.codex_cli_path` fields remain readable for
configuration compatibility but are not used by the in-task worker.

## Optional skill guidance

```bash
atlas-codex-install --project-dir . --config atlas.json --install-skill
```

This copies the ATLAS guidance skill into the documented user skill location,
`~/.agents/skills`. Pass `--skills-dir ./.agents/skills` when you explicitly
want a repository-local copy instead.

## Custom hook policy

Use `codex.hooks` in `atlas.json` when you want ATLAS to trigger only on selected Codex events:

```json
{
  "codex": {
    "hooks": {
      "SessionStart": true,
      "UserPromptSubmit": true,
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

Keep the compact final checkpoint on `Stop`; use advisory hooks for noisier events.

## Uninstall hooks

User-level:

```bash
atlas-codex-uninstall --user-level
```

Project-local:

```bash
atlas-codex-uninstall --project-dir .
```

This removes ATLAS hook config and, for the user-level default, the managed
guidance skill. It does not delete learned taxonomies or trace folders.

## More implementation detail

See [atlas_integration/codex/README.md](https://github.com/multi-agent-systems-failure-taxonomy/ATLAS/blob/main/atlas_integration/codex/README.md) for the adapter file map.
