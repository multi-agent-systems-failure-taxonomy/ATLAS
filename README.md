# ATLAS

### A failure-mode taxonomy layer for agents: reflect at meaningful boundaries, catch recurring mistakes, and learn from traces.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Claude Code](https://img.shields.io/badge/Claude_Code-hooks-D97757)](docs/CLAUDE_CODE.md)
[![Codex](https://img.shields.io/badge/Codex-hooks-111827)](docs/CODEX.md)
[![Runtime](https://img.shields.io/badge/runtime-harness_neutral-7C3AED)](atlas_runtime/)
[![Taxonomy](https://img.shields.io/badge/taxonomy-runtime_selected-0EA5E9)](finding/mast.json)
[![Tests](https://img.shields.io/badge/tests-pytest-16A34A)](tests/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

ATLAS helps agents notice their own recurring failure patterns before they submit work. It starts with the built-in MAST taxonomy, asks the agent for evidence-based reflection at configured gates, records the failure modes that actually appear, and can later generate or refine a taxonomy specialized to the user's traces.

The short version: ATLAS is not another task solver. It is a runtime supervision layer that gives an agent a structured way to ask, "what mistake am I about to repeat?"

![ATLAS runtime loop](docs/atlas_runtime_loop.png)

## Install

Requirements: Python 3.10 or newer.

```bash
python -m pip install "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
```

From a local checkout:

```bash
python -m pip install .
```

Optional provider extras:

```bash
python -m pip install "atlas-skill[anthropic] @ git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
python -m pip install "atlas-skill[bedrock] @ git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
```

Full install notes live in [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Quick start

Create `atlas.json` in the project that will run the agent:

```json
{
  "version": 1,
  "trace_output": "./atlas-program",
  "trace_root": "~/.atlas-skill/traces",
  "store_dir": "~/.atlas-skill/taxonomies",
  "atlas_model": "gpt-5",
  "inherit": null,
  "generation_threshold": 5,
  "generation_stops": false,
  "skip_judge": false,
  "k_init": 10,
  "k": 20,
  "refinement_stops": false,
  "advanced_refinement": false,
  "freeze": false,
  "max_retries": 3,
  "dashboard": true
}
```

Then choose the integration that matches your pipeline:

| Use case | Command | Full docs |
|---|---|---|
| Claude Code project | `atlas-claude-install --project-dir . --config atlas.json` | [Claude Code](docs/CLAUDE_CODE.md) |
| Codex project | `atlas-codex-install --project-dir . --config atlas.json` | [Codex](docs/CODEX.md) |
| One LLM call from a script | `atlas-single-run --config atlas.json --task "..." --model gpt-5` | [Single LLM](docs/SINGLE_LLM.md) |
| Existing trace folder | `atlas-import-traces --config atlas.json --traces ./traces` | [Taxonomies](docs/TAXONOMIES.md) |

Check the setup:

```bash
atlas-doctor --config atlas.json
```

## What ATLAS does at runtime

ATLAS has four moving pieces:

| Piece | Role |
|---|---|
| Taxonomy finding | Selects a stored taxonomy by `taxonomy_id`, or starts from built-in MAST when no taxonomy is inherited. |
| Runtime gates | Ask the agent to reflect only at configured checkpoints, tool boundaries, subagent boundaries, or final submission. |
| Trace capture | Stores canonical evidence from each task under the configured program trace output. |
| Learning lifecycle | Generates or refines taxonomies when enough traces accumulate, records usage/overlap metadata, then activates accepted taxonomies for later tasks. |

Repo and domain fields are display metadata only. Taxonomies are selected by `taxonomy_id`.

## Documentation

| Topic | Page |
|---|---|
| First successful run | [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) |
| Install options and credentials | [docs/INSTALLATION.md](docs/INSTALLATION.md) |
| Claude Code hooks | [docs/CLAUDE_CODE.md](docs/CLAUDE_CODE.md) |
| Codex hooks | [docs/CODEX.md](docs/CODEX.md) |
| Single-call / benchmark integration | [docs/SINGLE_LLM.md](docs/SINGLE_LLM.md) |
| Config files, prompts, hooks, judges | [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md) |
| Taxonomy records and inheritance | [docs/TAXONOMIES.md](docs/TAXONOMIES.md) |
| Traces, generation, refinement | [docs/TRACES_AND_LEARNING.md](docs/TRACES_AND_LEARNING.md) |
| Live dashboard and UID filtering | [docs/DASHBOARD.md](docs/DASHBOARD.md) |
| Local dashboard Web API | [docs/WEB_API.md](docs/WEB_API.md) |
| Harness-neutral runtime API | [docs/API_OR_RUNTIME.md](docs/API_OR_RUNTIME.md) |
| Common failures and fixes | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| Documentation index | [docs/README.md](docs/README.md) |

## Main commands

| Command | Purpose |
|---|---|
| `atlas-find` | List stored taxonomies or pick one interactively. |
| `atlas-dashboard` | Open the read-only localhost dashboard. |
| `atlas-traces` | Inspect trace state. |
| `atlas-import-traces` | Generate/store a taxonomy from existing traces. |
| `atlas-register-taxonomy` | Add a taxonomy JSON record to the store. |
| `atlas-doctor` | Validate config, paths, integrations, and optional dependencies. |
| `atlas-status` | Show program health: active taxonomy, pending traces, learning state, usage totals, and recent decisions. |
| `atlas-claude-install` / `atlas-claude-uninstall` | Manage Claude Code hooks. |
| `atlas-codex-install` / `atlas-codex-uninstall` | Manage Codex hooks. |
| `atlas-single-run` | Wrap one direct LLM task call with ATLAS. |

## Verify

```bash
python -m compileall atlas_runtime atlas_integration finding judge_types vendor
python -m pytest -q
git diff --check
```

## License

Apache-2.0. See [LICENSE](LICENSE).
