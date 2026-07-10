# Troubleshooting

Start with:

```bash
atlas-doctor --config atlas.json
atlas-status --config atlas.json
```

Use harness-specific checks when relevant:

```bash
atlas-doctor --config atlas.json --claude-code
atlas-doctor --config atlas.json --codex
```

## `atlas_model` cannot be called

Install the provider extra you need and make sure credentials are in the environment.

Anthropic:

```bash
python -m pip install "atlas-skill[anthropic] @ git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
```

Bedrock:

```bash
python -m pip install "atlas-skill[bedrock] @ git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
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
