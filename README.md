# 🧭 ATLAS

### A failure-mode taxonomy that watches an agent work, intervenes at meaningful checkpoints, and learns from its traces.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Claude Code](https://img.shields.io/badge/Claude_Code-blocking_hooks-D97757)](atlas_integration/claude_code/README.md)
[![Runtime](https://img.shields.io/badge/runtime-harness_neutral-7C3AED)](atlas_runtime/)
[![Taxonomy](https://img.shields.io/badge/taxonomy-dynamic_at_checkpoints-0EA5E9)](finding/mast.json)
[![Tests](https://img.shields.io/badge/tests-164_passing-16A34A)](tests/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

---

## ✨ What is ATLAS?

Agents often repeat the same *kinds* of mistakes: skipping verification, losing
track of requirements, persisting after a failed approach, or declaring success
too early.

ATLAS turns those recurring patterns into an active **failure-mode taxonomy**.
It begins with the general-purpose MAST taxonomy, observes the agent at
meaningful runtime boundaries, records the codes that actually fire, and can
generate a taxonomy specialized to the user's own traces.

> **The short version:** ATLAS gives an agent a structured way to notice its
> own mistakes before submission—without forcing a failure or an unnecessary
> edit.

### The interaction model

Every checkpoint follows the same two-perspective reflection:

1. **Observe → Map → Correlate** — inspect the recent trajectory like a neutral
   third-party reviewer and map only evidence-supported failure modes.
2. **Decide** — recognize that the trajectory is your own and change course
   only when necessary.

`none apply` is a valid result. ATLAS enforces that reflection happened in the
required shape; it cannot guarantee that the reflection is insightful.

---

## 🔄 How it works

```mermaid
flowchart LR
    A["Agent works"] --> B{"Meaningful boundary"}
    B -->|"sub-task / subagent"| C["Checkpoint reflection"]
    B -->|"tool failure"| D["Advisory nudge"]
    B -->|"completion"| E["Blocking final gate"]
    C --> A
    D --> A
    E -->|"repair required"| A
    E -->|"ready"| F["Trace captured"]
    F --> G{"Enough traces?"}
    G -->|"No"| H["Keep active taxonomy"]
    G -->|"Yes"| I["Generate + validate taxonomy"]
    I --> J["Activate on the next task"]
    J --> K["Refine as more traces arrive"]
```

| Stage | What happens |
|---|---|
| 🟦 **Start** | Resolve a stored taxonomy or begin with built-in MAST. |
| 🟨 **Runtime** | Surface taxonomy codes only when a checkpoint fires—never dump them into context at startup. |
| 🟥 **Gate** | Block completion until a valid reflection and final-gate decision exist. |
| 🟩 **Evidence** | Record fired codes, task IDs, reasoning, and evidence for the live dashboard. |
| 🟪 **Learning** | Capture one canonical trace and trigger generation or refinement at configured thresholds. |

---

## 🚀 Choose your path

| I want to… | Start here |
|---|---|
| Use ATLAS with **Claude Code** | [Claude Code quick start](#-claude-code-quick-start) |
| Wrap a **single LLM call** without a harness | [Single-LLM quick start](#-single-llm-quick-start) |
| Generate a taxonomy from **my existing traces** | [Import your own traces](#-bring-your-own-traces) |
| Pick a stored taxonomy interactively | [Taxonomy inheritance](#-taxonomy-inheritance) |
| Watch codes fire live | [Dashboard](#-live-dashboard) |
| Integrate another harness | [Public runtime API](#-public-runtime-api) |

---

## 📦 Install

**Requirements:** Python 3.10 or newer.

### From the release branch

```bash
python -m pip install "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
```

### From a local checkout

```bash
python -m pip install .
```

### Anthropic support

```bash
python -m pip install "atlas-skill[anthropic] @ git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
```

The installation provides:

| Command | Purpose |
|---|---|
| `atlas-claude-install` | Register project-local Claude Code hooks |
| `atlas-claude-uninstall` | Remove ATLAS hooks without disturbing unrelated settings |
| `atlas-single-run` | Run one no-harness model task through ATLAS |
| `atlas-import-traces` | Generate a stored taxonomy from existing traces |
| `atlas-find` | Resolve or interactively choose a taxonomy |
| `atlas-dashboard` | Open the live taxonomy dashboard |

> 🔐 **Credentials are never written into ATLAS configuration.** OpenAI-compatible
> calls use `OPENAI_API_KEY`; Anthropic uses its SDK environment credentials;
> Gemini uses `GEMINI_API_KEY` or `GOOGLE_API_KEY`.

---

## 🟠 Claude Code quick start

ATLAS uses Claude Code's installed hook system and verifies the required events
against the installed version **before writing any configuration**.

### 1. Install ATLAS into a project

```powershell
atlas-claude-install `
  --project-dir C:\path\to\project `
  --trace-output C:\path\to\atlas-program `
  --atlas-model gpt-5
```

On macOS or Linux:

```bash
atlas-claude-install \
  --project-dir /path/to/project \
  --trace-output /path/to/atlas-program \
  --atlas-model gpt-5
```

### 2. Use Claude Code normally

ATLAS registers seven project-local events:

| Event | Behavior | Can block? |
|---|---|:---:|
| `SessionStart` | Hold the active taxonomy and inject only standing checkpoint instructions | No |
| `TaskCompleted` | Reflect on the completed sub-task | **Yes** |
| `SubagentStop` | Reflect on that subagent's trajectory | **Yes** |
| `Stop` | Run the full final submission gate | **Yes** |
| `PostToolUseFailure` | Nudge after a real tool execution failure | No |
| `PostToolUse` | Detect failure signatures hidden in nominally successful output | No |
| `SessionEnd` | Capture an interrupted session if Stop did not already do so | No |

Claude Code may also request a proactive checkpoint after a major segment:

```text
ATLAS checkpoint request: finished implementing the parser
```

### 3. Uninstall safely

```powershell
atlas-claude-uninstall --project-dir C:\path\to\project
```

Upgrading from the old global skill?

```powershell
atlas-claude-install ... --migrate-legacy-global
```

This removes old ATLAS hook registrations while preserving unrelated Claude
settings. It does not delete the old skill directory.

<details>
<summary><strong>Claude discovery and custom learning endpoints</strong></summary>

ATLAS looks for Claude Code in this order:

1. `CLAUDE_CODE_EXECUTABLE`
2. `claude` on `PATH`
3. Common Windows, macOS, and Linux installation locations

For an OpenAI-compatible learning endpoint, persist only the credential
variable's name:

```powershell
$env:ATLAS_LEARNING_KEY = "..."

atlas-claude-install ... `
  --openai-base-url http://127.0.0.1:8742/v1 `
  --openai-api-key-env ATLAS_LEARNING_KEY
```

The value of `ATLAS_LEARNING_KEY` is never written to disk.

</details>

---

## 🔵 Single-LLM quick start

Use this path when your application owns the model call and there is no agent
harness.

### Command line

```powershell
$env:OPENAI_API_KEY = "..."

atlas-single-run `
  --task "Review this implementation and return the corrected result." `
  --model gpt-5 `
  --trace-output C:\path\to\atlas-program
```

Or provide a task file:

```bash
atlas-single-run \
  --task-file task.md \
  --model gpt-5 \
  --trace-output ./atlas-program
```

### Python callback API

```python
from atlas_integration.single_llm import SingleLLMConfig, run_single_llm


def my_message_callback(messages: list[dict[str, str]]) -> str:
    # Send the full message list to your provider and return assistant text.
    ...


result = run_single_llm(
    "Solve the task.",
    my_message_callback,
    SingleLLMConfig(
        trace_output="run/program",
        trace_root="run/traces",
        atlas_model="gpt-5",
    ),
)

print(result.answer)
```

The adapter pauses when the model requests a major-segment checkpoint, injects
the active taxonomy, validates the reflection, enforces the final gate, records
live firing evidence, captures the conversation, and closes the normal learning
lifecycle.

---

## 🧬 Taxonomy inheritance

Taxonomies are selected only by `taxonomy_id`. Repository and domain fields are
display metadata—not routing keys.

All supported CLIs use the same three forms:

| Invocation | Result |
|---|---|
| Omit `--inherit` | Fresh program starts with built-in MAST |
| `--inherit <taxonomy_id>` | Use that stored taxonomy |
| `--inherit` | Open the local visual taxonomy picker |

Example:

```bash
atlas-single-run \
  --task "Fix the failing test" \
  --model gpt-5 \
  --trace-output ./program \
  --inherit tax-20260619-example
```

The selected taxonomy is fixed for the current task. A newly generated or
refined successor becomes visible only to a later task.

---

## 📥 Bring your own traces

Generate and store an inheritable taxonomy whenever you already have traces:

```powershell
atlas-import-traces `
  --traces C:\path\to\trace-file-or-directory `
  --atlas-model gpt-5 `
  --repo my-project
```

The command:

1. Normalizes supported traces into the canonical schema.
2. Runs the vendored upstream ATLAS eight-stage generator.
3. Runs the support-based taxonomy check by default.
4. Allocates an ID only after acceptance.
5. Transactionally stores the taxonomy, traces, and generation artifacts.
6. Leaves the taxonomy dormant until selected with `--inherit`.

Rejected imports create no taxonomy record or taxonomy trace folder.

### Recommended trace format

Use one object per line in a `.jsonl` file:

```json
{
  "problem_id": "stable-task-or-attempt-id",
  "task": "task prompt or objective",
  "raw_trajectory": "plain-text execution trajectory",
  "metadata": {}
}
```

Also supported: canonical JSON, tau-bench, Codex sessions, event logs,
conversation/Forgecode records, KIRA trajectories, and directly supplied
plain-text trajectory files. Directories are scanned recursively for JSON and
JSONL files.

---

## 📊 Live dashboard

ATLAS can launch a local read-only dashboard automatically with the first task.
It updates as checkpoint evidence arrives and follows taxonomy successors
without restarting.

Run it manually:

```bash
atlas-dashboard \
  --trace-output ./atlas-program \
  --store-dir ~/.atlas-skill/taxonomies
```

The dashboard shows:

- the active taxonomy and latest successor;
- code descriptions and categories;
- total firings and unique task IDs;
- firings per task;
- checkpoint reasoning and evidence;
- taxonomy-version-scoped counts.

It binds to localhost and opens `http://127.0.0.1:8765/` by default. Use
`--port 0` for any free port or `--no-browser` to suppress browser launch.

---

## 🧠 Learning lifecycle

ATLAS separates **runtime interaction** from **taxonomy learning**.

### Fresh start: MAST → generated taxonomy

```text
Task traces:  1 ── 2 ── 3 ── 4 ── 5
                                  │
                                  ▼
                         Generate candidate
                                  │
                                  ▼
                      Support-based validation
                           │             │
                      accepted       rejected
                           │             │
                           ▼             ▼
                    activate later   keep MAST +
                                     wait for N more
```

- Default generation threshold: **N = 5** traces.
- Success and failure traces count equally.
- Generation input is outcome-blind.
- Acceptance requires at least **5 ACTIVE codes**, each supported by at least
  one distinct trace.
- Activation waits until no task is running.

### Refinement

| Phase | Default | Meaning |
|---|---:|---|
| Initial refinement | `K_init = 10` | First refinement after a program begins using a real taxonomy |
| Standard refinement | `K = 20` | Later refinements since the program's previous accepted refinement |

Refinement creates a new taxonomy ID and a successor link—it never overwrites
the previous taxonomy. Other programs follow the successor on their next task
while preserving their own counters.

<details>
<summary><strong>Generation and validation details</strong></summary>

- The support judge processes at most four trace units per call.
- Oversized traces are split into context-safe chunks.
- Chunk findings are merged back to the original trace.
- One code receives at most one support vote per distinct trace.
- Unknown codes, duplicate assignments, and mismatched quotes are ignored.
- Invalid judge JSON receives one bounded repair retry.
- Failed or omitted units contribute no support and do not crash the pass.
- A rejected taxonomy receives no ID and does not consume pending traces.
- After rejection, generation retries after another `N` traces arrive.

</details>

<details>
<summary><strong>Basic vs. advanced refinement</strong></summary>

Basic refinement:

```text
current taxonomy + frozen trace set
        ↓
replacement candidate
        ↓
structural validation + diff
        ↓
accepted successor
```

With `--advanced-refinement`, ATLAS adds one support-judge pass. Reported
issues receive one repair-model call; the repaired candidate is not judged a
second time.

</details>

---

## 🎛️ Configuration

Claude Code exposes the main lifecycle controls directly:

| Option | Default | Effect |
|---|---:|---|
| `--generation-threshold` | `5` | Traces required before initial generation |
| `--generation-stops` | off | Block the threshold-crossing task while generation runs |
| `--skip-judge` | off | Skip Reflection Judge + refiner at end of generation (default: refine before accept) |
| `--k-init` | `10` | Traces before a program's first refinement |
| `--k` | `20` | Traces between later refinements |
| `--refinement-stops` | off | Block while refinement runs |
| `--advanced-refinement` | off | Add judge-guided refinement repair |
| `--max-retries` | `3` | Completed final-gate repair opportunities before honest unresolved release |
| `--failure-throttle-calls` | `5` | Minimum tool calls between reactive nudges |
| `--failure-recency-seconds` | `30` | Time-based duplicate-nudge suppression |
| `--no-dashboard` | off | Let an outer application own dashboard lifecycle |

### Storage

Default writable locations:

```text
~/.atlas-skill/
├── taxonomies/
└── traces/
```

Override them with:

| Variable | Purpose |
|---|---|
| `ATLAS_HOME` | Change the shared ATLAS data root |
| `ATLAS_STORE_DIR` | Override only the taxonomy store |
| `ATLAS_TRACE_ROOT` | Override only the learning-trace store |
| `ATLAS_DISABLE_DASHBOARD=1` | Disable automatic dashboard launch |

Explicit CLI and API paths always take precedence.

---

## 🔌 Public runtime API

Custom harnesses can use the engine directly:

```python
from atlas_runtime import (
    GenerationTrace,
    end_session,
    pre_submission,
    record_trace,
    start_session,
)

session = start_session(
    trace_output="./program",
    atlas_model="gpt-5",
)

# Deliver session.delivery.runtime_protocol and, only at a checkpoint,
# the relevant session.delivery.taxonomy content.

decision = pre_submission(session, model_gate_text)

record_trace(
    session,
    GenerationTrace(
        problem_id="task-001",
        task="Fix the parser",
        raw_trajectory=complete_trace,
        metadata={"harness": "custom"},
    ),
)

result = end_session(session)
```

The engine owns taxonomy selection, persistence, generation, validation,
refinement, lineage, and dashboard lifecycle. The harness owns prompt delivery,
model execution, and trace collection.

---

## 🛡️ What ATLAS enforces—and what it cannot

| Claim | Reality |
|---|---|
| Reflection ran | ✅ Shape is machine-checked |
| At least one code has evidence, or `none apply` is justified | ✅ Machine-checked |
| Each repair receives a fresh reflection and the completed-repair limit is respected | ✅ Machine-checked |
| Claude Code completion can be blocked | ✅ Through blocking hooks |
| Reactive tool-failure nudge is mandatory | ❌ Advisory only |
| Reflection is genuinely insightful | ❌ Content quality is not mechanically knowable |
| A fired code proves the task answer is wrong | ❌ It identifies a process pattern, not benchmark correctness |

The static [`SKILL.md`](SKILL.md) contains only standing interaction behavior.
The active taxonomy is deliberately **not** always loaded into context; it is
surfaced at runtime checkpoints.

---

## 🗂️ Data model

```json
{
  "taxonomy_id": "tax-20260619-example",
  "repo": "display-only/repository",
  "domain": "Discovered domain",
  "codes": [
    {
      "id": "A.1",
      "name": "Failure name",
      "description": "Observable definition",
      "category": "A"
    }
  ]
}
```

- `taxonomy_id` is the only selector.
- `repo` and `domain` are display-only metadata.
- MAST is a built-in floor, not a stored picker record.
- Generated and refined taxonomies are immutable records connected by
  successor links.

---

## 🧪 Verification

```bash
python -m pytest -q
```

The current release includes **164 passing tests** covering:

- taxonomy finding and interactive selection;
- MAST fallback and canonical schema;
- Claude Code hook contracts and retry guards;
- zero-tool, sub-task, subagent, failure-nudge, and final-gate paths;
- live evidence and dashboard updates;
- trace capture and outcome-blind learning;
- generation, validation, retry, activation, and lineage;
- basic and advanced refinement;
- imported-trace taxonomy generation;
- install/uninstall behavior and writable storage defaults;
- direct single-LLM checkpoints and repairs.

---

## 🧹 Uninstall and data

Remove Claude Code hooks:

```bash
atlas-claude-uninstall --project-dir /path/to/project
```

ATLAS does not automatically delete learned taxonomies or traces. User data
remains under `~/.atlas-skill/` unless custom paths were supplied.

Trace retention is intentionally conservative: data is not expired
automatically. ATLAS warns when a trace folder exceeds 10,000 records or its
oldest file is more than 90 days old.

---

## 📚 Repository map

| Path | Purpose |
|---|---|
| [`atlas_runtime/`](atlas_runtime/) | Harness-neutral lifecycle and learning engine |
| [`atlas_integration/claude_code/`](atlas_integration/claude_code/) | Claude Code runtime skin |
| [`atlas_integration/single_llm/`](atlas_integration/single_llm/) | Direct model-call adapter |
| [`finding/`](finding/) | Taxonomy selection, MAST, store, and picker |
| [`vendor/atlas/`](vendor/atlas/) | Vendored upstream eight-stage ATLAS generator |
| [`tests/`](tests/) | Unit, integration, lifecycle, and packaging coverage |

---

<div align="center">

### Start general. Observe honestly. Learn the failures that actually recur.

`MAST → runtime evidence → generated taxonomy → refinement`

</div>
