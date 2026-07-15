# ATLAS Claude Code integration

Claude Code runtime skin. It delivers the active taxonomy only at reflection
gates, records live firing evidence, and captures one canonical learning trace
for each completed main-agent turn. Taxonomy generation, refinement, and
storage remain engine-owned and are invoked through the public lifecycle API.

## Natural-language assets

Claude Code can run ATLAS through the installed Python hooks, or a harness can
read the natural-language assets directly and supply its own execution layer:

- `atlas_integration/claude_code/assets/standing_prompt.md` — standing session
  instruction delivered at `SessionStart`.
- `atlas_runtime/assets/checkpoint_reflection.md` — shared checkpoint
  reflection contract used by blocking/advisory gates.
- `atlas_integration/claude_code/assets/final_gate_tail.md` — Claude-specific
  final submission tail appended to the shared checkpoint prompt.
- `judge_types/assets/<judge>/system.md` and `user.md` — simple judge prompts
  for Selection, Mapping, Coverage, Quality, Calibration.
- `judge_types/reflection_judge/assets/*.md` — Reflection Judge staged prompts.
- `vendor/atlas/pipeline/assets/*.md` — taxonomy-generation prompts.

The Python modules remain useful as controllers: they load context, render
assets, validate JSON, record traces, and call the lifecycle API. Direct
natural-language import is for harnesses that want to own those mechanics
themselves.

Install the package, then install project-local hooks:

```powershell
atlas-claude-install `
  --project-dir C:\path\to\project `
  --trace-output C:\path\to\program-traces `
  --trace-root C:\path\to\learning-traces `
  --atlas-model claude-sonnet-4-6
```

Registrations invoke the installed module rather than a source-checkout file.
Uninstall with:

```powershell
atlas-claude-uninstall --project-dir C:\path\to\project
```

When upgrading from the old global `atlas-failure-modes` hooks, add
`--migrate-legacy-global` to either command. Unrelated Claude settings are
preserved.

For the Codex-style interactive experience in every Claude Code project, use:

```powershell
atlas-claude-install --user-level
atlas-doctor --claude-code
```

User-level installation writes `~/.claude/atlas-skill.json` and merges hooks
into `~/.claude/settings.json`. With the same base runtime root and task group,
Claude Code and Codex share the taxonomy and refinement lineage for a project.
The native Claude worker is one Agent subtask in the active session; it does
not require a separately supplied model API key, standalone `claude -p`
process, or second login. The default browser selector can be replaced with
the inline numbered surface via `--selector-surface inline`.

ATLAS pins the first resolved project and task group to Claude's stable session
ID. Resuming that session from another shell, changing directories, or entering
a nested repository does not reopen the selector or change its taxonomy.

The matching reversible cleanup command is
`atlas-claude-uninstall --user-level`; unrelated Claude settings remain.

The installer verifies the locally installed Claude Code binary before writing
`.claude/settings.local.json`. Built-in events:

- `SessionStart`: select and hold the session taxonomy; inject only standing
  checkpoint instructions.
- `UserPromptSubmit`: resolve the selector, hold an initial substantive task,
  and begin each later episode.
- `SessionEnd`: idempotent fallback capture for interrupted sessions that did
  not finish through the Stop gate.
- `TaskCompleted`: blocking sub-task checkpoint.
- `SubagentStop`: blocking subagent checkpoint, except for a signed taxonomy
  receipt, which is captured without recursively gating the learning worker.
- `Stop`: blocking full submission gate.
- `PostToolUse`: nonblocking nudge when a nominally successful tool response
  contains a failure signature.
- `PostToolUseFailure`: nonblocking nudge for actual tool execution failures.

All built-ins are installed by default for backwards compatibility, but you can
reduce noise for a project. Disable an event:

```powershell
atlas-claude-install `
  --project-dir C:\path\to\project `
  --trace-output C:\path\to\program-traces `
  --atlas-model claude-sonnet-4-6 `
  --disable-hook SubagentStop
```

Restrict successful/failed tool-result nudges to specific Claude Code tool
matchers:

```powershell
atlas-claude-install `
  --project-dir C:\path\to\project `
  --trace-output C:\path\to\program-traces `
  --atlas-model claude-sonnet-4-6 `
  --post-tool-use-matchers Bash,Edit,Write `
  --post-tool-use-failure-matchers Bash
```

The config-file equivalent is the top-level `built_in_hooks` object:

```json
{
  "built_in_hooks": {
    "SubagentStop": false,
    "PostToolUse": ["Bash", "Edit", "Write"],
    "PostToolUseFailure": {
      "enabled": true,
      "matchers": ["Bash"]
    }
  }
}
```

Only `PostToolUse` and `PostToolUseFailure` support matcher lists. Other
built-in events are on/off.

Taxonomy content is surfaced only when a checkpoint fires. Accepted reflections
write taxonomy-version-scoped runtime evidence to
`<trace-output>/.atlas-runtime-evidence.json`; the live dashboard overlays it
without changing the taxonomy record.

Observed on Claude Code 2.1.181: `TaskCompleted` applies to explicit Claude
task objects. A main task that creates no task object is still covered by
`Stop`, but that version does not emit `TaskCompleted` for the main task.

On a successful Stop release (including bounded retry-guard release), the
adapter records the Claude JSONL delta since the previous accepted Stop as one
`GenerationTrace` and calls `atlas_runtime.record_trace()` followed by
`end_session()`. The next user turn opens a new runtime episode under the same
conversation lineage. The `SessionEnd` hook captures only an open episode that
Stop did not already commit. This lets the existing engine trigger generation
or refinement at its configured thresholds without duplicating learning logic
in the harness.

With `claude_code.learning_backend: "claude_subagent"`, `end_session()` freezes
eligible episode traces and queues one proposal-only job. The next
`SessionStart` or `UserPromptSubmit` claims it and instructs the active Claude
session to launch one native Agent subtask against `prompt.txt` and the strict
output schema. Its signed receipt is captured through `SubagentStop`.
Foreground reconciliation checks the claim, snapshot hash, evidence ids,
project version, and idle episode boundary before activation. Trigger and
finish notices are delivered exactly once to the originating conversation on
its next hook event.

When the final Stop reflection returns `REPAIR_REQUIRED`, the hook blocks and
grants one repair opportunity. The next completion attempt is blocked again
for a fresh reflection scoped to the repair trajectory. `Repair attempts used`
is checked against the hook-owned completed-repair counter. With the default
limit of three, Claude receives three repair-and-re-evaluate opportunities;
only a clean `READY_TO_SUBMIT` releases early, while a third still-unresolved
re-evaluation releases as an honest unresolved report to prevent an infinite
loop.

Claude discovery checks `CLAUDE_CODE_EXECUTABLE`, `claude` on `PATH`, and
common Windows, macOS, and Linux locations. The discovered installation must
contain every required event and blocking/additional-context contract.

For subprocess-based learning backends, `--openai-base-url` may be persisted.
Use `--openai-api-key-env NAME` to persist only the name of an inherited
environment variable; credential values are never written to disk.

Lifecycle controls exposed by the installer include generation threshold and
blocking, initial/standard refinement thresholds, refinement blocking,
advanced refinement, failure-nudge throttling, and `--skip-judge` (which
bypasses the end-of-generation Reflection Judge + refiner step). Run
`atlas-claude-install --help` for the exact options. `--no-dashboard`
persistently suppresses integration-managed dashboards when an outer harness
owns the dashboard.

## Custom hooks

Beyond the seven built-in events, you can bind the same reflection<->refinement
loop to **any** Claude Code event without writing Python. Use the
`atlas-claude-add-hook` CLI after `atlas-claude-install` has placed a
config:

```powershell
# Block before any Bash call; require an ATLAS reflection before it runs.
atlas-claude-add-hook `
  --project-dir C:\path\to\project `
  --name pre-bash-gate `
  --event PreToolUse `
  --matcher Bash `
  --mode blocking

# Emit a non-blocking nudge whenever the user submits a new prompt.
atlas-claude-add-hook `
  --project-dir C:\path\to\project `
  --name on-user-prompt `
  --event UserPromptSubmit `
  --mode advisory
```

The CLI rewrites `.claude/atlas-skill.json` and refreshes
`.claude/settings.local.json` so Claude Code picks up the new registration on
its next session. Inspect or remove:

```powershell
atlas-claude-list-hooks --project-dir C:\path\to\project
atlas-claude-remove-hook --project-dir C:\path\to\project --name pre-bash-gate
```

What each `--mode` does:

- **`blocking`** — On the first fire, exit 2 with a reflection prompt scoped
  to the activity around this event. On subsequent fires, parse the
  transcript for a valid `ATLAS reflection:` block matching the checkpoint
  ID; release with exit 0 when valid. Retries are bounded by `--max-retries`
  (same hook-owned retry guard the built-in gates use); after the limit, the
  hook releases and logs the reason. The submission-only
  `READY_TO_SUBMIT`/`REPAIR_REQUIRED` language is intentionally omitted.
- **`advisory`** — Each fire emits an `additionalContext` nudge with a
  reflection prompt; Claude is never blocked. Any reflection block the
  assistant writes is harvested by the next blocking gate.

You can also declare custom hooks directly in `.claude/atlas-skill.json`
under the top-level `"custom_hooks"` array; each entry is
`{name, event, mode, matcher?}`. The installer treats two custom hooks on the
same event with different matchers as separate `settings.local.json` entries
(so e.g. one Bash gate + one Edit nudge co-exist cleanly), and
`atlas-claude-uninstall` removes every custom registration alongside the
built-ins.

Available events: `SessionStart`, `SessionEnd`, `Stop`, `TaskCompleted`,
`SubagentStop`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
`PreCompact`, `Notification`, `UserPromptSubmit`. Built-in events keep
their built-in handler regardless; a custom hook on a built-in event
*adds* a second registration that runs alongside it.

## Programs

| File | Purpose |
|---|---|
| [`__init__.py`](__init__.py) | Public exports |
| [`config.py`](config.py) | `ClaudeCodeConfig` dataclass + built-in/custom hook specs — serialized to `.claude/atlas-skill.json`, loaded by every hook |
| [`custom.py`](custom.py) | Reflection runtime for `CustomHookSpec` entries: `custom_blocking_checkpoint` + `custom_advisory` reuse the same reflection-shape validator as the built-in gates |
| [`dispatcher.py`](dispatcher.py) | Single command entry point. Built-in events route by `hook_event_name`; custom hooks route via `--custom <spec_name>` |
| [`install.py`](install.py) | `atlas-claude-install` CLI: write project-local or user-level settings + `atlas-skill.json`, register built-in events + every `custom_hooks` entry, verify Claude Code binary contract |
| [`learning_jobs.py`](learning_jobs.py) | Claude policy facade for shared durable jobs, threshold polling, and foreground reconciliation |
| [`subagent_protocol.py`](subagent_protocol.py) | Claude Agent-instruction facade for the shared signed receipt protocol |
| [`session_routes.py`](session_routes.py) | Claude-namespaced facade for stable conversation scope and fresh-conversation routing |
| [`browser_picker.py`](browser_picker.py) | Claude-namespaced facade for the shared localhost picker transport |
| [`native_worker.py`](native_worker.py) | Legacy detached-worker compatibility entry point; native in-session learning does not invoke it |
| [`manage_hooks.py`](manage_hooks.py) | `atlas-claude-add-hook` / `remove-hook` / `list-hooks` CLIs to mutate `custom_hooks` and refresh `settings.local.json` in one command |
| [`prompts.py`](prompts.py) | Claude Code standing instruction + Claude-specific final-gate wrapper around the shared checkpoint prompt |
| [`reflection.py`](reflection.py) | Compatibility re-export for the shared `atlas_runtime.reflection` parser |
| [`runtime.py`](runtime.py) | Shared hook behavior: `session_start`, `blocking_checkpoint`, `post_tool`, transcript capture, lifecycle wiring |
| [`state.py`](state.py) | Claude Code per-session hook state (mode, pending checkpoints); runtime evidence is recorded by `atlas_runtime.evidence` |
| [`transcript.py`](transcript.py) | Claude Code JSONL transcript readers/writers |
| [`uninstall.py`](uninstall.py) | `atlas-claude-uninstall` CLI: remove the hook registrations, preserve unrelated settings |

## Sub-folders

- [`hooks/`](hooks/) — One file per Claude Code hook event
  (`SessionStart`, `UserPromptSubmit`, `SessionEnd`, `TaskCompleted`, `SubagentStop`, `Stop`,
  `PostToolUse`, `PostToolUseFailure`). Each file exports a thin `handle`
  function that the dispatcher routes to; all real behavior lives in
  [`runtime.py`](runtime.py).

Host-neutral implementations live in
[`../interactive/`](../interactive/). Keep Claude hook contracts and transcript
handling here; place selector, route, job, and receipt behavior in the shared
package.
