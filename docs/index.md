# ATLAS

**A failure-mode taxonomy layer for agents: reflect at meaningful boundaries,
catch recurring mistakes, and learn from traces.**

![ATLAS runtime loop](atlas_runtime_loop.png)

ATLAS gives an agent a structured way to notice recurring mistakes at runtime,
record evidence, and generate or refine task-specific failure-mode taxonomies
from completed traces.

Runs start from **MAST** — the Multi-Agent System failure Taxonomy from
["Why Do Multi-Agent LLM Systems Fail?" (Cemri et al., 2025)](https://arxiv.org/abs/2503.13657),
shipped as a built-in 14-code adaptation. At configured gates the agent
reflects on its recent trajectory (Observe → Correlate → Map → Decide), a
blocking final gate runs before submission, and completed traces feed taxonomy
generation and refinement. ATLAS is not a task solver; your harness keeps
owning model execution.

## Quickstart

Install:

```bash
python -m pip install "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
```

Create `atlas.json` in the project that will run the agent:

```json
{
  "version": 1,
  "trace_output": "./atlas-program",
  "atlas_model": "gpt-5"
}
```

Then choose the integration that matches your pipeline:

| Use case | Command | Full docs |
|---|---|---|
| Claude Code project | `atlas-claude-install --project-dir . --config atlas.json` | [Claude Code](CLAUDE_CODE.md) |
| Codex project | `atlas-codex-install --project-dir . --config atlas.json` | [Codex](CODEX.md) |
| One LLM call from a script | `atlas-single-run --config atlas.json --task "..." --model gpt-5` | [Single LLM](SINGLE_LLM.md) |
| Existing trace folder | `atlas-import-traces --config atlas.json --traces ./traces` | [Taxonomies](TAXONOMIES.md) |
| Your own harness | `from atlas_runtime import start_session, ...` | [Pipeline integration](INTEGRATION.md) |

Check the setup:

```bash
atlas-doctor --config atlas.json
```

## Where to start

- New to the terminology? [Concepts](CONCEPTS.md) defines the vocabulary and
  the runtime loop.
- Want to see real output first? [An example run](EXAMPLE_RUN.md) shows the
  reflections, the final gate, and the dashboard.
- Ready to wire it up? [Getting started](GETTING_STARTED.md) is the 5-minute
  path; [Configuration reference](CONFIGURATION.md) covers every
  `atlas.json` field.
