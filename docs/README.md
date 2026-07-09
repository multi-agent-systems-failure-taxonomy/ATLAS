# ATLAS documentation

This folder is the detailed reference for ATLAS. The repository homepage stays intentionally short; operational details live here.

## Start here

| Goal | Page |
|---|---|
| Learn the vocabulary and the runtime loop | [CONCEPTS.md](CONCEPTS.md) |
| See real reflections, gates, and dashboard output | [EXAMPLE_RUN.md](EXAMPLE_RUN.md) |
| Get one project running quickly | [GETTING_STARTED.md](GETTING_STARTED.md) |
| Install ATLAS and optional model providers | [INSTALLATION.md](INSTALLATION.md) |
| Look up any `atlas.json` field | [CONFIGURATION.md](CONFIGURATION.md) |
| Understand the learning lifecycle | [TRACES_AND_LEARNING.md](TRACES_AND_LEARNING.md) |
| Customize hooks, prompts, judges, or model profiles | [CUSTOMIZATION.md](CUSTOMIZATION.md) |

## Integrations

| Integration | Page |
|---|---|
| Claude Code | [CLAUDE_CODE.md](CLAUDE_CODE.md) |
| Codex | [CODEX.md](CODEX.md) |
| Direct single-LLM calls, scripts, notebooks, benchmarks | [SINGLE_LLM.md](SINGLE_LLM.md) |
| Custom harnesses | [API_OR_RUNTIME.md](API_OR_RUNTIME.md) |
| Harness-author contract, privacy, and redaction | [INTEGRATION.md](INTEGRATION.md) |

## Runtime data

| Topic | Page |
|---|---|
| Taxonomy records, inheritance, and importing existing taxonomies | [TAXONOMIES.md](TAXONOMIES.md) |
| Trace storage, generation thresholds, refinement thresholds | [TRACES_AND_LEARNING.md](TRACES_AND_LEARNING.md) |
| Live dashboard, task UID filtering, and local monitoring | [DASHBOARD.md](DASHBOARD.md) |
| Local dashboard HTTP endpoints and response shapes | [WEB_API.md](WEB_API.md) |
| Program health CLI and common runtime failures | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |

## Web docs

The dependency-free web landing page is [index.html](index.html). It can be
served directly by GitHub Pages from the `docs/` folder while the Markdown pages
remain readable in GitHub's normal file view.

## Lower-level package maps

These pages are useful when changing internals:

- [atlas_runtime/README.md](../atlas_runtime/README.md)
- [atlas_integration/README.md](../atlas_integration/README.md)
- [finding/README.md](../finding/README.md)
- [judge_types/README.md](../judge_types/README.md)
- [tests/README.md](../tests/README.md)
