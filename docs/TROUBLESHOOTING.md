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

## Native taxonomy learning cannot launch

The conversation hooks can run even when the detached taxonomy worker cannot.
Check the host-specific doctor output:

```bash
atlas-doctor --codex
atlas-doctor --claude-code
```

For Codex, a desktop-app executable may be visible but denied to background
processes. Install and sign in to the standalone Codex CLI, or set
`codex.codex_cli_path` to a runnable executable. Confirm with
`codex login status`.

For Claude Code, confirm `claude auth status` succeeds. You may set
`CLAUDE_CODE_EXECUTABLE` or `claude_code.claude_cli_path` when discovery finds
the wrong executable.

No external provider API key is needed for `codex_subagent` or
`claude_subagent`; these backends reuse the host CLI account.

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
