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

Use `--selector-surface browser` (the default) or
`--selector-surface inline` to override `codex.selector_surface` for one
install.

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
    "selector_surface": "browser",
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

With `session_selector` set to `prompt`, a new Codex conversation opens the
session-bound localhost taxonomy library from its first real
`UserPromptSubmit`. `SessionStart` only recovers an existing selection, so
background host work and spawned agent sessions cannot open unsolicited browser
windows. The browser applies the choice directly to the conversation before it
reports success, and the held substantive request becomes the episode task.

For an unbound project, MAST is recommended alongside the compatible stored
taxonomies and `No taxonomy`. The picker runs in a detached, time-bounded
process and writes a durable activation receipt after updating the Codex state.
Choosing a stored taxonomy establishes it as the shared taxonomy for the
project task group immediately. Once bound, later
conversations see its human-facing display name as the recommended compatible
choice. MAST remains a numbered option: choosing it in a bound project creates
a durable conversation-specific `fresh-*` task group and learns from zero while
preserving the shared default. `No taxonomy` disables ATLAS gates and trace
capture for only that conversation.

`learning_backend: "codex_subagent"` uses a native subagent in the active
Codex task and does not require a standalone CLI login or external API key.
Every hook in an already selected conversation polls the durable project state:
it reconciles completed receipts, checks the generation or refinement threshold,
and idempotently queues any missing job. On the next `UserPromptSubmit` or
supported `SessionStart` boundary (`startup`, `resume`, or context compaction),
the active agent receives a claimed task and launches the taxonomy subagent
while normal work continues. Context compaction is included so a long-running
desktop task can dispatch a queued job even when that Codex build does not emit
`UserPromptSubmit`. Unselected internal sessions do not poll or claim learning
jobs. The subagent reads an immutable outcome-blind snapshot and returns a
staged receipt through `SubagentStop`; hook reconciliation alone owns
validation and activation.

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
| `SessionStart` | Recover ATLAS state and dispatch queued native learning at startup, resume, or context compaction. |
| `UserPromptSubmit` | Open the taxonomy library for a new user conversation and handle episode boundaries. |
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

By default this writes `atlas-failure-modes` under the documented user skill
directory, `~/.agents/skills`. Pass `--skills-dir ./.agents/skills` for a
repository-local copy.

## Uninstall

```bash
atlas-codex-uninstall --project-dir .
```

This removes only ATLAS hook registrations from `.codex/hooks.json` and deletes
`.codex/atlas-skill.json`. To also remove the optional skill files:

```bash
atlas-codex-uninstall --project-dir . --remove-skill
```

For the zero-config user-level integration, use
`atlas-codex-install --user-level` and reverse it with
`atlas-codex-uninstall --user-level`.

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
| [`learning_jobs.py`](learning_jobs.py) | Codex policy facade for shared durable jobs and threshold polling. |
| [`subagent_protocol.py`](subagent_protocol.py) | Codex claim-instruction facade for the shared receipt protocol. |
| [`session_routes.py`](session_routes.py) | Codex-namespaced facade for shared fresh-conversation routing. |
| [`browser_picker.py`](browser_picker.py) | Codex-namespaced facade for the shared localhost picker transport. |
| [`native_worker.py`](native_worker.py) | Legacy detached-worker compatibility entry point; the native runtime does not invoke it. |

Host-neutral implementations live in
[`../interactive/`](../interactive/). Keep Codex event parsing and transcript
normalization here; place selector, route, job, and receipt behavior in the
shared package.
