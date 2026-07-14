# ATLAS

### A failure-mode taxonomy layer for agents: reflect at meaningful boundaries, catch recurring mistakes, and learn from traces.

[![Paper](https://img.shields.io/badge/paper-PDF-B31B1B)](docs/atlas_paper.pdf)
[![Docs](https://img.shields.io/badge/docs-website-2563EB)](https://multi-agent-systems-failure-taxonomy.github.io/ATLAS/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**Paper:** [Adaptive Failure Taxonomies as Feedback for LLM-Agent Improvement Procedures](docs/atlas_paper.pdf)

**Documentation:** [multi-agent-systems-failure-taxonomy.github.io/ATLAS](https://multi-agent-systems-failure-taxonomy.github.io/ATLAS/) · [Concepts](docs/CONCEPTS.md) · [Getting started](docs/GETTING_STARTED.md)

Procedures that improve LLM agents act on the failures in execution traces: a
best-of-N selector picks the best of several attempts, a program-search loop
rewrites the agent after failed runs, and a runtime monitor reflects before an
action commits. All three need feedback that names *why* a trajectory failed, in
a form that aggregates across runs. Scalar rewards discard the reason. Free-form
reflections are unstructured and per-trace. Hand-authored taxonomies such as
MAST, from ["Why Do Multi-Agent LLM Systems Fail?" (Cemri et al., 2025)](https://arxiv.org/abs/2503.13657),
fix the vocabulary before observing the agent, its roles, or the target domain.

ATLAS induces the vocabulary instead. It reads a target system's own traces and
generates a compact set of evidence-grounded failure codes, with no
hand-authored codes and no per-trace annotation, then passes those codes back to
the improvement procedure alongside each trace. This repository packages that
idea as a runtime skill: it supervises an agent against a taxonomy at meaningful
boundaries, records the failures that actually occur, and generates or refines a
taxonomy specialized to your own traces. When no taxonomy is configured it starts
from a built-in 14-code adaptation of MAST.

ATLAS is not a task solver. It is a diagnostic feedback layer that gives an agent
a structured way to ask, "what mistake am I about to repeat?"

## Adaptive failure taxonomies

An ATLAS taxonomy is a set of 15 to 30 failure codes induced from a system's own
traces, organized along three fixed axes. The axes follow MAST's empirical
clustering of failure modes; the concrete codes, role labels, descriptions, and
evidence patterns are induced per system:

| Axis | Scope | Example code |
|---|---|---|
| System-level | Arises in any agent system | `Context_Exhaustion`, `Premature_Termination` |
| Role-specific | Tied to a discovered component role | `Checker_Rubber_Stamps_Solver's_Output` |
| Domain-specific | Requires task knowledge | `Algorithm_Mismatch`, `Physical_Law_Violation` |

The same induced vocabulary is a reusable feedback interface for more than one
improvement procedure. The paper,
[Adaptive Failure Taxonomies as Feedback for LLM-Agent Improvement Procedures](docs/atlas_paper.pdf),
evaluates three:

1. **Best-of-N trajectory selection.** As judges on Terminal-Bench 2.0,
   ATLAS-Judge reaches 89.9% accuracy (+15 points over Pass@1) and beats judges
   that use a fixed taxonomy or none.
2. **Evolutionary agent-system optimization.** As mutation feedback,
   taxonomy-coded diagnoses beat free-form reflection across competitive
   programming, math, STEM QA, and discrete reasoning (OlympiadBench 87.9% to
   91.9% on a 655-problem held-out set).
3. **Runtime feedback.** For SWE-agent on SWE-bench Verified Mini, codes improve
   over free-form reflection in both in-prompt and external-judge use. This
   runtime setting is what the skill in this repository implements.

On TRAIL (117 expert-annotated GAIA traces), induced codes align with the human
gold at Cohen's kappa 0.725, more faithfully than TRAIL's hand-crafted
vocabulary.

## Runtime Integration - How it works

![ATLAS runtime loop](docs/atlas_runtime_loop.png)

1. A task starts. ATLAS selects the active taxonomy: an inherited stored
   taxonomy, or built-in MAST when none is configured.
2. At configured boundaries (checkpoints, tool failures, subagent stops), the
   agent reflects against the taxonomy and repairs when evidence demands it.
3. A final submission gate validates completion. Blocking adapters hold the
   answer until reflection passes or retries are exhausted honestly; Codex
   uses a compact single-pass checkpoint because its desktop Stop continuation
   is not guaranteed to redeliver the hook.
4. One canonical trace is recorded per run; interactive conversations record
   one trace for each completed assistant episode.
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
Map:       MAST-3 (Step repetition); evidence supports the match.
Decide:    One focused repair: verify the installed package version
           before the next run.
```

Mapping no codes ("none apply") is a valid outcome. Blocking integrations
require the same reflection and allow a bounded number of repairs. Codex keeps
the long reflection internal and records the compact final checkpoint in one
Stop callback. Everything the gates record is browsable live in the
[dashboard](docs/DASHBOARD.md).

A full walkthrough with dashboard screenshots is in
[docs/EXAMPLE_RUN.md](docs/EXAMPLE_RUN.md). Try the dashboard yourself with
`python -m examples.dashboard_demo`.

## Install

Requirements: Python 3.10 or newer.

```bash
python -m pip install "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
```

From a local checkout: `python -m pip install .`

ATLAS's provider-backed learning calls support Anthropic,
OpenAI(-compatible), Gemini, and AWS Bedrock model IDs. Optional extras
(`[anthropic]`, `[bedrock]`) and credential setup live in
[docs/INSTALLATION.md](docs/INSTALLATION.md).

## Interactive quick start

For ordinary Codex or Claude Code conversations, no `atlas.json` and no
separate model API key are required:

```bash
# Codex, for all projects
atlas-codex-install --user-level
atlas-doctor --codex

# Claude Code, for all projects
atlas-claude-install --user-level
atlas-doctor --claude-code
```

Run both installers to share learned taxonomy state across both hosts for the
same Git project. The signed-in host CLI performs taxonomy generation and
refinement in a detached worker while the main conversation continues. Codex
also requires a separately runnable `codex` CLI; the doctor detects desktop
installations that cannot launch background jobs.

See [Interactive setup](docs/INTERACTIVE_SETUP.md) for the selector, episode
trace contract, trigger/completion notices, shared project storage, and
uninstall commands.

## Project and pipeline quick start

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
| Codex all projects | `atlas-codex-install --user-level` | [Interactive setup](docs/INTERACTIVE_SETUP.md) |
| Claude Code all projects | `atlas-claude-install --user-level` | [Interactive setup](docs/INTERACTIVE_SETUP.md) |
| Claude Code project | `atlas-claude-install --project-dir . --config atlas.json` | [Claude Code](docs/CLAUDE_CODE.md) |
| Codex project | `atlas-codex-install --project-dir . --config atlas.json` | [Codex](docs/CODEX.md) |
| One LLM call from a script | `atlas-single-run --config atlas.json --task "..." --model gpt-5` | [Single LLM](docs/SINGLE_LLM.md) |
| Existing trace folder | `atlas-import-traces --config atlas.json --traces ./traces` | [Taxonomies](docs/TAXONOMIES.md) |
| Your own harness | `from atlas_runtime import start_session, ...` | [Integration](docs/INTEGRATION.md) |

Check the setup:

```bash
atlas-doctor --config atlas.json
```

## Results

Full evaluation artifacts (per-question result rows, the exact taxonomies used,
and replication steps) live in [runs/](runs/):

| Experiment | Headline |
|---|---|
| [OfficeQA Pro, agent harness](runs/OfficeQA/) | 44.4% → **51.9%** official scorer (Bedrock Haiku 4.5, 133 questions, same harness both arms) |
| [Circle packing (n=26)](runs/Circle-Packing/) | On [SkyDiscover](https://github.com/skydiscover-ai/skydiscover)'s search harness: baselines never reach 0.997 of AlphaEvolve's record; with ATLAS the search reaches it in **20 evals** (peak 0.999735) |

## Documentation

| Topic | Page |
|---|---|
| Vocabulary and the runtime loop | [docs/CONCEPTS.md](docs/CONCEPTS.md) |
| Real reflections, gates, and dashboard output | [docs/EXAMPLE_RUN.md](docs/EXAMPLE_RUN.md) |
| First successful run | [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) |
| User-level Codex and Claude setup | [docs/INTERACTIVE_SETUP.md](docs/INTERACTIVE_SETUP.md) |
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
| Supported hosts and current limits | [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) |
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

## Related

The original ATLAS taxonomy-induction pipeline (the research code this skill
builds on) lives on the
[`paper-pipeline`](https://github.com/multi-agent-systems-failure-taxonomy/ATLAS/tree/paper-pipeline)
branch and is vendored unchanged under [vendor/atlas](vendor/atlas/).

## License

Apache-2.0. See [LICENSE](LICENSE).
