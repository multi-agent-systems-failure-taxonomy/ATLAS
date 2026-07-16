# AdaMAST

### Failure-mode taxonomies for agents, grounded in the traces they actually produce.

[![Paper](https://img.shields.io/badge/paper-PDF-B31B1B)](docs/adamast_paper.pdf)
[![Docs](https://img.shields.io/badge/docs-website-2457D6)](https://multi-agent-systems-failure-taxonomy.github.io/ATLAS/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-1F8A70)](LICENSE)

AdaMAST adds a diagnostic feedback layer to an agent. It checks work at
meaningful boundaries, records evidence about recurring failures, and learns a
project-specific taxonomy from completed traces. Your existing agent or
harness keeps owning the task.

**Paper:** [Adaptive Failure Taxonomies as Feedback for LLM-Agent Improvement Procedures](docs/adamast_paper.pdf)

**Documentation:** [Website](https://multi-agent-systems-failure-taxonomy.github.io/ATLAS/) · [Interactive setup](docs/INTERACTIVE_SETUP.md) · [Architecture](docs/ARCHITECTURE.md)

## Install in one minute

Requirements: Python 3.10 or newer.

```bash
python -m pip install --upgrade "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"
```

Install AdaMAST once for the host you use:

**Codex**

```bash
adamast-codex-install --user-level
adamast-doctor --codex
```

**Claude Code**

```bash
adamast-claude-install --user-level
adamast-doctor --claude-code
```

Start a **new conversation** after installation. AdaMAST opens the local taxonomy
library and lets you choose:

- **MAST** to begin with the built-in general taxonomy;
- a **stored taxonomy** to share the project's learned vocabulary;
- **No taxonomy** to disable AdaMAST for that conversation.

No `adamast.json`, external model API key, standalone host CLI, or second login
is required for this interactive path. Run both installers when you want Codex
and Claude Code to share taxonomy state for the same Git project.

## What happens in a conversation

1. AdaMAST resolves the Git project and task group, then pins one taxonomy.
2. The agent continues normal work. Checkpoints inspect only recent activity.
3. A completed assistant episode becomes one canonical trace.
4. At five eligible traces, AdaMAST queues taxonomy generation by default.
5. One native host subagent proposes a candidate while the main agent keeps
   working. After exact-span checks, a separate support-review subagent must
   approve every replacement code before foreground activation.
6. The first refinement review occurs after ten additional traces; later
   reviews occur every twenty traces by default.

If a project already has a learned taxonomy, MAST remains available as a
numbered choice. Selecting it creates an isolated `fresh-*` task group for that
conversation and leaves the shared project taxonomy unchanged.

Learn how this is kept durable and race-safe in
[Native taxonomy learning](docs/NATIVE_LEARNING.md).

## Choose your integration

| Goal | Start here |
|---|---|
| Use AdaMAST in every Codex task | `adamast-codex-install --user-level` · [Codex guide](docs/CODEX.md) |
| Use AdaMAST in every Claude Code session | `adamast-claude-install --user-level` · [Claude Code guide](docs/CLAUDE_CODE.md) |
| Configure hooks for one repository | [Project setup](docs/GETTING_STARTED.md) |
| Wrap one direct model call | `adamast-single-run` · [Single LLM guide](docs/SINGLE_LLM.md) |
| Learn from an existing trace folder | `adamast-import-traces` · [Taxonomies](docs/TAXONOMIES.md) |
| Integrate a custom agent harness | `from adamast_runtime import start_session` · [Runtime API](docs/INTEGRATION.md) |
| Inspect an example without configuring a provider | `python -m examples.dashboard_demo` · [Example run](docs/EXAMPLE_RUN.md) |

## Runtime loop

![AdaMAST runtime loop](docs/adamast_runtime_loop.png)

At a checkpoint, the agent follows a fixed sequence:

```text
Observe:   What concretely happened or was omitted?
Correlate: Which evidence-supported cause explains it?
Map:       Which active failure code applies, if any?
Decide:    Continue, or make one focused repair.
```

`none apply` is valid. AdaMAST does not manufacture a failure just to force a
change. Blocking hosts can hold completion for bounded repair rounds; Codex
uses a compact single-pass Stop checkpoint because some desktop builds do not
redeliver hook continuations.

## Why adaptive taxonomies

Improvement procedures need feedback that preserves *why* a trajectory failed.
Scalar rewards discard the reason. Free-form reflection is difficult to
aggregate. A fixed taxonomy cannot know the target agent's roles, tools, or
domain before observing it.

AdaMAST learns a compact set of evidence-grounded failure codes from the target
system's own traces. Until a learned taxonomy is active, runs start from the
built-in 14-code adaptation of MAST from
["Why Do Multi-Agent LLM Systems Fail?" (Cemri et al., 2025)](https://arxiv.org/abs/2503.13657).

Generated codes are organized along three stable axes:

| Axis | Scope | Example |
|---|---|---|
| System-level | Can arise in any agent system | Context exhaustion |
| Role-specific | Tied to a discovered component role | Checker rubber-stamps solver output |
| Domain-specific | Requires task knowledge | Algorithm mismatch |

The paper evaluates this vocabulary as feedback for best-of-N selection,
evolutionary agent optimization, and runtime reflection. On TRAIL, induced
codes align with expert annotations at Cohen's kappa 0.725.

## Repository map

| Path | Responsibility |
|---|---|
| [`adamast_runtime/`](adamast_runtime/) | Harness-neutral sessions, gates, traces, learning, validation, activation, and evidence |
| [`adamast_integration/interactive/`](adamast_integration/interactive/) | Shared selector, browser, routes, native jobs, and receipt protocol |
| [`adamast_integration/codex/`](adamast_integration/codex/) | Codex hooks and transcript adapter |
| [`adamast_integration/claude_code/`](adamast_integration/claude_code/) | Claude Code hooks, gates, and transcript adapter |
| [`adamast_integration/single_llm/`](adamast_integration/single_llm/) | Direct single-model adapter |
| [`finding/`](finding/) | MAST, taxonomy registry, display metadata, and local views |
| [`judge_types/`](judge_types/) | Taxonomy and reflection judges |
| [`AdaMAST_as_a_Judge/`](AdaMAST_as_a_Judge/) | Judge-focused evaluation checks |
| [`vendor/adamast/`](vendor/adamast/) | Maintained in-tree fork of the research generation pipeline |
| [`examples/`](examples/) | Runnable demonstrations |
| [`runs/`](runs/) | Evaluation artifacts and reproduction notes |

The complete ownership rules are in [Architecture](docs/ARCHITECTURE.md). Each
package has its own README with a file-level map.

## Results

Reported summaries, exact taxonomies, and reproduction instructions live in
[`runs/`](runs/). Per-question rows and raw scorer output are not included, so
the headline numbers below cannot be independently recomputed from this
repository alone.

| Experiment | Headline |
|---|---|
| [OfficeQA Pro](runs/OfficeQA/) | 44.4% → **51.9%** official scorer, same 133-question harness in both arms |
| [Circle packing, n=26](runs/Circle-Packing/) | AdaMAST-guided search reaches 0.997 of the AlphaEvolve record in **20 evaluations** |

The paper reports AdaMAST-Judge at 89.9% accuracy on Terminal-Bench 2.0 and an
87.9% to 91.9% held-out improvement for evolutionary optimization on a
655-problem set.

## Documentation

| Need | Page |
|---|---|
| First interactive install | [Interactive setup](docs/INTERACTIVE_SETUP.md) |
| See a complete run | [Example run](docs/EXAMPLE_RUN.md) |
| Understand terms | [Concepts](docs/CONCEPTS.md) |
| Understand code ownership | [Architecture](docs/ARCHITECTURE.md) |
| Understand native workers | [Native taxonomy learning](docs/NATIVE_LEARNING.md) |
| Configure one project | [Getting started](docs/GETTING_STARTED.md) |
| Look up every field | [Configuration reference](docs/CONFIGURATION.md) |
| Debug setup | [Troubleshooting](docs/TROUBLESHOOTING.md) |
| Browse all docs | [Documentation index](docs/README.md) |

## Main commands

| Command | Purpose |
|---|---|
| `adamast-doctor` | Validate paths, configuration, hooks, and host contracts. |
| `adamast-status` | Show the active taxonomy, traces, learning state, and recent decisions. |
| `adamast-find` | List or select stored taxonomies. |
| `adamast-dashboard` | Open the read-only localhost runtime dashboard. |
| `adamast-traces` | Inspect trace state. |
| `adamast-import-traces` | Generate a taxonomy from existing traces. |
| `adamast-codex-install` / `adamast-codex-uninstall` | Manage Codex hooks. |
| `adamast-claude-install` / `adamast-claude-uninstall` | Manage Claude Code hooks. |
| `adamast-single-run` | Wrap one direct model task with AdaMAST. |

## Contributing

Development setup, verification commands, and package boundaries are in
[CONTRIBUTING.md](CONTRIBUTING.md). Release steps are in
[RELEASING.md](RELEASING.md).

The original research pipeline is available on the
[`paper-pipeline`](https://github.com/multi-agent-systems-failure-taxonomy/ATLAS/tree/paper-pipeline)
branch. A maintained, locally patched fork is included under
[`vendor/adamast/`](vendor/adamast/); its provenance and change categories are
documented in [`VENDORED.md`](vendor/adamast/VENDORED.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
