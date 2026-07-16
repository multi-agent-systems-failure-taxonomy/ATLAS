# ATLAS 5-minute start

This page covers explicit project-local and pipeline integration. For the
shortest user-level Codex or Claude Code path, use
[Interactive setup](INTERACTIVE_SETUP.md).

If you want the full reference, start from the [documentation home](index.md).

## 1. Install

From GitHub:

```bash
python -m pip install "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
```

From a local checkout:

```bash
cd /path/to/ATLAS
python -m pip install .
```

Optional Anthropic SDK support:

```bash
python -m pip install "atlas-skill[anthropic] @ git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
```

Optional AWS Bedrock bearer-token support:

```bash
python -m pip install "atlas-skill[bedrock] @ git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
```

For Bedrock, set `AWS_BEARER_TOKEN_BEDROCK` and `AWS_REGION` /
`AWS_DEFAULT_REGION` in your shell. ATLAS uses boto3's Bedrock Converse API
for this credential form.

ATLAS never stores credential values. Set provider keys in your environment
instead.

## 2. Create one config file

Create `atlas.json` in your project:

```json
{
  "version": 1,
  "trace_output": "./atlas-program",
  "atlas_model": "gpt-5"
}
```

Use `atlas_model` for ATLAS generation, judge, and refinement calls. If your
own program has a task-solving model, keep that separate.

Relative paths are resolved relative to the config file. Every other field has
a sensible default; the full reference is [CONFIGURATION.md](CONFIGURATION.md).

## 3. Check the install

```bash
atlas-doctor --config atlas.json
```

For Claude Code projects:

```bash
atlas-doctor --config atlas.json --claude-code
```

For Codex projects:

```bash
atlas-doctor --config atlas.json --codex
```

Warnings usually mean "ATLAS can run, but a useful optional capability may be
missing." Errors mean the requested setup is not ready.

## 4A. Use ATLAS with Claude Code

For every Claude Code project with native in-session learning, the shorter path
is `atlas-claude-install --user-level`. The command below is the explicit,
project-local provider-backed path.

Install project-local hooks:

```bash
atlas-claude-install --project-dir . --config atlas.json
```

Start Claude Code in that project. ATLAS will:

1. start with inherited taxonomy if configured, otherwise built-in MAST;
2. deliver checkpoint instructions at configured hook boundaries;
3. require the final submission gate before completion;
4. record one canonical trace for each completed assistant episode;
5. trigger generation/refinement when configured thresholds are reached.

Useful hook customization examples:

```bash
# Do not fire the built-in subagent checkpoint.
atlas-claude-install --project-dir . --config atlas.json --disable-hook SubagentStop

# Only nudge after selected successful tool calls.
atlas-claude-install --project-dir . --config atlas.json --post-tool-use-matchers Bash,Edit,Write

# Add a custom blocking gate before Bash calls.
atlas-claude-add-hook --project-dir . --name pre-bash --event PreToolUse --matcher Bash --mode blocking
```

List installed custom hooks:

```bash
atlas-claude-list-hooks --project-dir .
```

Remove ATLAS hooks without deleting learned traces or taxonomies:

```bash
atlas-claude-uninstall --project-dir .
```

## 4B. Use ATLAS with Codex hooks

For every Codex project with native in-task learning, the shorter path is
`atlas-codex-install --user-level`. The command below is the explicit,
project-local provider-backed path.

Install project-local Codex hooks:

```bash
atlas-codex-install --project-dir . --config atlas.json
```

This writes `.codex/hooks.json` and `.codex/atlas-skill.json`. Open `/hooks`
inside Codex and trust the ATLAS hooks before relying on them.

Default Codex events:

1. `SessionStart`: recover standing ATLAS context for a selected conversation.
2. `UserPromptSubmit`: open the taxonomy library for a new conversation and handle episode boundaries.
3. `Stop`: capture the compact final checkpoint and commit the episode once.
4. `SubagentStop`: capture a checkpoint when present without blocking.
5. `PostToolUse`: add advisory nudges after selected failed tool outputs.

Optional skill guidance:

```bash
atlas-codex-install --project-dir . --config atlas.json --install-skill
```

Remove it with:

```bash
atlas-codex-uninstall --project-dir .
```

## 4C. Use ATLAS around one LLM call

This path is for scripts, notebooks, benchmarks, or any application where you
own the model call.

```bash
atlas-single-run \
  --config atlas.json \
  --task "Solve the task, then pass through ATLAS before final answer." \
  --model gpt-5
```

The `--model` flag is the task-solving model. `atlas_model` in `atlas.json` is
still the ATLAS judge/generation/refinement model.

## 5. Watch the dashboard

If `dashboard` is true, integrations can launch the dashboard automatically.
To open it manually:

```bash
atlas-dashboard \
  --trace-output ./atlas-program \
  --store-dir ~/.atlas-skill/taxonomies
```

The dashboard is read-only and binds to localhost by default.

## 6. Verify data is being written

After a run, inspect trace state:

```bash
atlas-traces status --config atlas.json
```

List stored taxonomies:

```bash
atlas-find --list
```

If `--inherit` is omitted, the run starts with built-in MAST. MAST is not stored
as a picker record. Generated/refined taxonomies become stored records only
after acceptance.

## 7. Common first-run choices

The fields most people touch first:

| Choice | Default | When to change it |
|---|---:|---|
| `generation_threshold` | `5` | Raise it if early traces are noisy or not representative. |
| `freeze` | `false` | Turn on for inference-only evaluation: record traces/evidence, but skip generation and refinement. |
| `repair_rounds` | `3` | Final-gate repair opportunities before honest unresolved release (`max_retries` is the legacy alias). |

Every field, with defaults and semantics, is in
[CONFIGURATION.md](CONFIGURATION.md).

## 8. Where to customize

Most user-facing behavior is now in Markdown or JSON assets. Start with
[`CUSTOMIZATION.md`](CUSTOMIZATION.md) before editing Python.
