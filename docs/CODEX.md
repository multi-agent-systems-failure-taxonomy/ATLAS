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

1. `SessionStart`: deliver standing context or initialize taxonomy selection.
2. `UserPromptSubmit`: hold the first task, resolve the selection, and resume it.
3. `Stop`: capture the compact final checkpoint and commit the episode in one callback.
4. `SubagentStop`: capture a compact subagent checkpoint when present without blocking.
5. `PostToolUse`: add advisory nudges after selected failed tool outputs.

## Conversation selector

Enable the Codex-only in-chat selector with automatic project scoping:

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

A new conversation recommends MAST for an unbound project, lists compatible
stored taxonomies with short domain/origin metadata, and includes `No taxonomy`.
The first task is held while the user chooses, then resumes automatically. A
stored taxonomy becomes the shared project/task-group taxonomy. `No taxonomy`
disables ATLAS gates and trace capture only for that conversation.

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
an isolated `codex exec` process that reuses the signed-in Codex account. It
does not require `OPENAI_API_KEY` or another user-supplied model credential.
The child runs with hooks disabled, no approvals, a read-only sandbox, and an
immutable project/task-group evidence snapshot.

The fifth eligible episode triggers generation by default. MAST remains active
while the child produces a proposal. The child cannot publish a taxonomy: it
writes a receipt that the normal hook coordinator validates and activates only
when no episode is active. The first refinement review occurs after 10 new
episodes and later reviews every 20; a review may retain the current taxonomy
when the evidence does not justify a change.

The trigger notice appears in the hook event that queues the worker. Codex
hooks cannot inject into an idle task asynchronously, so the finished notice
appears exactly once on the conversation's next lifecycle event. A failed or
stale result leaves MAST or the current taxonomy active and preserves traces.

Optional worker controls are `codex.worker_model`,
`codex.codex_cli_path`, and `codex.worker_timeout_seconds`. Normally the CLI is
discovered from `CODEX_CLI_PATH`, and the worker uses the session's default
model.

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

```bash
atlas-codex-uninstall --project-dir .
```

This removes ATLAS hook config from the project. It does not delete learned taxonomies or trace folders.

## More implementation detail

See [atlas_integration/codex/README.md](https://github.com/multi-agent-systems-failure-taxonomy/ATLAS/blob/main/atlas_integration/codex/README.md) for the adapter file map.
