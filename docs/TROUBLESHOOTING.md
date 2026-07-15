# Troubleshooting

Start with:

```bash
atlas-doctor --config atlas.json
atlas-status --config atlas.json
```

For a zero-config user-level installation, omit `--config`:

```bash
atlas-doctor --codex
atlas-doctor --claude-code
```

Use harness-specific checks when relevant:

```bash
atlas-doctor --config atlas.json --claude-code
atlas-doctor --config atlas.json --codex
```

## Commands are installed but PowerShell cannot run them

On Windows, Python's user-level `Scripts` directory may not be on `PATH`.
Run the module entry points directly until that directory is added:

```powershell
python -m atlas_runtime.doctor --codex
python -m atlas_integration.codex.install --user-level
```

An npm Codex installation may also resolve bare `codex` to `codex.ps1`, which
PowerShell can block under a restrictive execution policy. Use the equivalent
command shim without changing the machine policy:

```powershell
codex.cmd --version
codex.cmd
```

## A gate did not fire

Blocking gates fail open by design: if the hook process crashes or is killed
at the harness's per-hook timeout, the agent continues and the gate is
silently skipped — an ATLAS bug must never brick your session. To confirm
gating actually happened, check `[atlas]` stderr lines, the per-gate records
in `<trace_output>/decisions.log`, and `atlas-status` (a finished session
with no final-gate evidence means the gate was skipped).

## `atlas_model` cannot be called

Install the provider extra you need and make sure credentials are in the environment.

Anthropic:

```bash
python -m pip install "atlas-skill[anthropic] @ git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
```

Bedrock:

```bash
python -m pip install "atlas-skill[bedrock] @ git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
export AWS_BEARER_TOKEN_BEDROCK="..."
export AWS_REGION="us-east-1"
```

Do not print or commit credentials.

## Hooks installed but not firing

Check:

1. the hook config was installed into the project you are actually running;
2. the harness trusts/enables project-local hooks;
3. `atlas.json` points to a valid trace output;
4. custom hook matchers use the host's actual event/tool names.

For broad tool matchers such as `Bash`, prefer adding a `command_pattern` so a
custom hook fires only for the intended recurring command.

For Codex, open `/hooks` and trust the ATLAS hooks.

For Claude Code, list installed ATLAS custom hooks:

```bash
atlas-claude-list-hooks --project-dir .
```

## The taxonomy browser reopens after resuming Claude Code

Current releases bind each Claude session ID to its first resolved ATLAS
program. This prevents Claude's resumed or changed `cwd` from looking like a
new conversation. Upgrade and reinstall the user-level hooks:

```bash
python -m pip install --upgrade "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
atlas-claude-install --user-level
atlas-doctor --claude-code
```

The first hook after upgrading also migrates any existing selected or disabled
session state into the binding. It should not ask for the taxonomy again.
An exact legacy inline reply such as `MAST` is also recovered from the saved
Claude transcript before a pending session can launch the browser.

## A taxonomy browser opens beside an unrelated Codex task

If the browser page names `memories` as the project, it came from a Codex
host-maintenance conversation rather than the visible project. Current releases
bypass `~/.codex/memories` before ATLAS routing. They also recover an exact
legacy inline reply such as `MAST` from a pending task's transcript before
opening a browser.

## The conversation still says MAST after learning finished

MAST may remain in persisted selection state as the conversation's lineage
seed. Once generation or refinement activates a successor, host context should
instead name the active taxonomy's display name and immutable ID and direct the
agent to its codes. Run `atlas-status` to compare the active taxonomy with the
generation and refinement states. If status shows a learned taxonomy but the
conversation still calls MAST pinned, upgrade and reinstall the host hooks.

## Native taxonomy learning cannot launch

The conversation hooks can run even when a taxonomy worker cannot be
dispatched. Check the host-specific doctor output:

```bash
atlas-doctor --codex
atlas-doctor --claude-code
```

For Codex, the native taxonomy job is claimed on `SessionStart` or
`UserPromptSubmit`, then launched by the active agent as a subagent. A queued
job can remain safely dormant between tasks. Check the project program's
`learning_jobs` directory and the next hook's developer context; no standalone
Codex CLI is required.

For Claude Code, inspect the next `SessionStart` or `UserPromptSubmit` hook
context for `ATLAS native taxonomy learning is ready`. The active Claude agent
must launch exactly one native Agent subtask for the requested phase and return
its receipt through `SubagentStop`. A separate support-review phase follows a
valid replacement proposal. A standalone `claude -p` login and
`claude_code.claude_cli_path` are not used by the native path.

No external provider API key is needed for `codex_subagent` or
`claude_subagent`; each uses its active host session.

## Final gate retries unexpectedly

The final gate checks the shape of the reflection and decision. It can verify that evidence was cited or that `none apply` was justified; it cannot guarantee the reasoning is insightful.

If the agent keeps failing the gate, inspect the generated trace and the gate prompt assets listed in [CUSTOMIZATION.md](CUSTOMIZATION.md).

## Dashboard does not open

Try launching it manually:

```bash
atlas-dashboard --trace-output ./atlas-program --store-dir ~/.atlas-skill/taxonomies
```

If the port is busy, stop the old dashboard process or configure a different port through the integration that launches it.

## Taxonomy does not appear in the picker

MAST is built in and intentionally not a store record. It does not appear in `list_all`.

Generated, refined, imported, or registered taxonomies appear only after they are stored as JSON records under the configured store directory.

## Trace folders are growing

ATLAS keeps traces by default so future generation and refinement have evidence. For long-running programs, keep trace roots outside the repository and archive old folders periodically.

If another system needs the evidence, configure `evidence_export` so ATLAS
writes a session-end JSON snapshot to a separate file or directory sink. This
does not prune or move the original trace folder.
