# ATLAS

### A failure-mode taxonomy layer for agents: reflect at meaningful boundaries, catch recurring mistakes, and learn from traces.

[![Docs](https://img.shields.io/badge/docs-website-2563EB)](https://multi-agent-systems-failure-taxonomy.github.io/ATLAS/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**Documentation:** [multi-agent-systems-failure-taxonomy.github.io/ATLAS](https://multi-agent-systems-failure-taxonomy.github.io/ATLAS/) · [Concepts](docs/CONCEPTS.md) · [Getting started](docs/GETTING_STARTED.md)

ATLAS helps agents notice their own recurring failure patterns before they
submit work. It starts from MAST — the Multi-Agent System failure Taxonomy
from ["Why Do Multi-Agent LLM Systems Fail?" (Cemri et al., 2025)](https://arxiv.org/abs/2503.13657),
shipped here as a built-in 14-code adaptation — asks the agent for
evidence-based reflection at configured gates, records the failure modes that
actually appear, and later generates or refines a taxonomy specialized to your
own traces.

ATLAS is not another task solver. It is a runtime supervision layer that gives
an agent a structured way to ask, "what mistake am I about to repeat?"

## How it works

![ATLAS runtime loop](docs/atlas_runtime_loop.png)

1. A task starts. ATLAS selects the active taxonomy — an inherited stored
   taxonomy, or built-in MAST when none is configured.
2. At configured boundaries (checkpoints, tool failures, subagent stops), the
   agent reflects against the taxonomy and repairs when evidence demands it.
3. A final submission gate blocks completion until the reflection passes or
   retries are exhausted honestly.
4. One canonical trace is recorded at session end.
5. After enough traces, ATLAS generates a task-specific taxonomy (or refines
   the active one). Accepted taxonomies become inheritable records for future
   runs.

New to the terminology? Start with [docs/CONCEPTS.md](docs/CONCEPTS.md).

## What it looks like

At a checkpoint, the agent reflects on its recent trajectory against the
active taxonomy in a fixed shape:

```text
Observe:   The last two Bash runs failed with the same ImportError; no
           dependency check ran between attempts.
Correlate: Retrying an identical command without new information.
Map:       MAST-3 (Step repetition) — evidence supports the match.
Decide:    One focused repair — verify the installed package version
           before the next run.
```

Mapping no codes ("none apply") is a valid outcome. Before the final answer is
released, a blocking gate requires the same reflection and allows a bounded
number of repairs. Everything the gates record is browsable live in the
[dashboard](docs/DASHBOARD.md).

A full walkthrough with dashboard screenshots is in
[docs/EXAMPLE_RUN.md](docs/EXAMPLE_RUN.md). Try the dashboard yourself with
`python -m examples.dashboard_demo`.

## Install

Requirements: Python 3.10 or newer.

```bash
python -m pip install "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
```

From a local checkout: `python -m pip install .`

ATLAS's own learning calls support Anthropic, OpenAI(-compatible), Gemini, and
AWS Bedrock model IDs. Optional extras (`[anthropic]`, `[bedrock]`) and
credential setup live in [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Quick start

Create `atlas.json` in the project that will run the agent:

```json
{
  "version": 1,
  "trace_output": "./atlas-program",
  "atlas_model": "gpt-5"
}
```

Every field, its default, and when to change it:
[docs/CONFIGURATION.md](docs/CONFIGURATION.md).

Then choose the integration that matches your pipeline:

| Use case | Command | Full docs |
|---|---|---|
| Claude Code project | `atlas-claude-install --project-dir . --config atlas.json` | [Claude Code](docs/CLAUDE_CODE.md) |
| Codex project | `atlas-codex-install --project-dir . --config atlas.json` | [Codex](docs/CODEX.md) |
| One LLM call from a script | `atlas-single-run --config atlas.json --task "..." --model gpt-5` | [Single LLM](docs/SINGLE_LLM.md) |
| Existing trace folder | `atlas-import-traces --config atlas.json --traces ./traces` | [Taxonomies](docs/TAXONOMIES.md) |
| Your own harness | `from atlas_runtime import start_session, ...` | [Integration](docs/INTEGRATION.md) |

Check the setup:

```bash
atlas-doctor --config atlas.json
```

## Documentation

| Topic | Page |
|---|---|
| Vocabulary and the runtime loop | [docs/CONCEPTS.md](docs/CONCEPTS.md) |
| Real reflections, gates, and dashboard output | [docs/EXAMPLE_RUN.md](docs/EXAMPLE_RUN.md) |
| First successful run | [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) |
| Every `atlas.json` field | [docs/CONFIGURATION.md](docs/CONFIGURATION.md) |
| Install options and credentials | [docs/INSTALLATION.md](docs/INSTALLATION.md) |
| Claude Code hooks | [docs/CLAUDE_CODE.md](docs/CLAUDE_CODE.md) |
| Codex hooks | [docs/CODEX.md](docs/CODEX.md) |
| Single-call / benchmark integration | [docs/SINGLE_LLM.md](docs/SINGLE_LLM.md) |
| Harness-author contract and privacy | [docs/INTEGRATION.md](docs/INTEGRATION.md) |
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

## Contributing

Development setup, verification commands, and package maps are in
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
