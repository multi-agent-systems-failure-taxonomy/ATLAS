# ATLAS_as_a_Judge

An LLM-as-judge that turns an agent execution trace into a **causal graph of
failure points** — kept strictly separate from any success/fail verdict.

## The idea

Failure-mode *presence* and *count* do **not** determine task outcome (the
relationship is non-stationary and confounded across tasks and agent
architectures). So this judge does not claim outcomes. It produces a neutral
structural artifact — a graph — and a **separate** process (Component B) reads
that graph to decide whether the task failed. The graph carries no verdict, but
must be *sufficient* for B.

## Architecture

| Component | Job | Status |
|---|---|---|
| **A** — graph builder | trace -> causal failure graph | in progress |
| ↳ **A1** — node creation | identify failure points + spans | **built (this module)** |
| ↳ **A2** — edges + leveling | causal edges + ancestor hierarchy | **built** |
| **B** — graph reader | graph -> success/fail | deferred |

The graph is a **multi-parent, leveled DAG**, built **forward** (we do not start
from the outcome — the agent may not know if it was right). No cycles except
self-loops. Cause/effect are **edge roles**, not node labels: a node can be both
(a mediator), including across agents in a MAS. A big failure cascade can be
*recovered* and still succeed; a small one can *leak through* and fail. Recovery
vs. leak-through — not failure count — is what ties the graph to outcome, and
that is Component B's problem, not the graph's.

## A1 — node creation (this module)

A **failure point** is a piece of the trace that matches ≥ 1 taxonomy failure
mode. The taxonomy is the *sole* definition of failure and is assumed correct.

- **Node** = one fresh fault *onset*, anchored to a **unit index**. It may carry
  multiple codes; a new independent fault at a later unit is a new node.
- **Span** = onset-unit → next-onset-unit (spans tile the trace in unit space).
  Downstream consequence/recovery units are absorbed into the preceding span —
  a span is a *territory*, not a measure of the error's extent.

### Anchoring: unit index, not quoted text

The trace is first **pre-split deterministically** into numbered units
(`splitter.py`): a JSON-with-`steps` trajectory (hover/GEPA shape) becomes unit 0
= context + one unit per step; anything else falls back to line units. The LLM
then anchors each failure point by returning an **integer `unit_index`** — it
never transcribes trace text. This eliminates the verbatim-quote-locating
failure mode (paraphrase / escaped `\n` `\"` in JSON tool-calls / non-ASCII
mangling) that dropped ~half the onsets in the first design. Validation is a
simple range-check; spans are sliced deterministically in unit space.

### How it runs

All three passes are made by an **LLM agent (default `claude-sonnet-4-5`)**:

1. **forward pass** — read unit 0 → last, mark fresh faulty units by index.
2. **backward pass** — read last → unit 0, catch faults only obvious in hindsight.
3. **merge** — deduplicated **union** of unit indices (same unit → one node,
   union codes). Deterministic union fallback if the merge call fails.
4. **tile** (deterministic) — validate/dedup/sort indices, tile spans onset-unit
   → next-onset-unit.

Merge default is **union** (max recall); a precision cleanup pass is deferred.

### Live status

Smoke-tested on 5 hover traces via Bedrock Sonnet 4.5
(`us.anthropic.claude-sonnet-4-5-20250929-v1:0`): **0 unlocatable drops / 0
warnings**, coherent A+C code assignments (retrieval duplication, query drift,
no-final-verdict, role confusion), multi-code units, contiguous unit-space
tiling.

### Usage

```python
from ATLAS_as_a_Judge import identify_failure_points, LLMAgent
from atlas_runtime.taxonomy_data import Taxonomy
import json

tax = Taxonomy.from_dict(json.load(open("taxonomy.json")))   # or a flat {codes:[...]} dict / MAST

result = identify_failure_points(
    task="Verify the claim ...",
    trajectory=raw_trace_text,      # a JSON-with-steps string, or any text
    taxonomy=tax,
    agent=LLMAgent(model="claude-sonnet-4-5"),
)

for fp in result.failure_points:
    print(fp.index, fp.unit_index, fp.codes, (fp.start_unit, fp.end_unit), fp.description)
```

Inject a fake `transport` into `LLMAgent` to run offline (see `tests/`).

## Files

| File | Purpose |
|---|---|
| `a1_nodes.py` | A1 pipeline: detect (forward/backward) → merge → tile |
| `splitter.py` | Deterministic pre-split into numbered units (JSON `steps`, line fallback) |
| `llm_agent.py` | `LLMAgent` — model-agnostic JSON agent (default Sonnet 4.5) |
| `models.py` | `Unit`, `Onset` (pre-tiling), `FailurePoint` (node), `A1Result` |
| `prompts.py` | Loads + builds the three prompts from `assets/` |
| `assets/` | Editable Markdown prompts: `a1_forward.md`, `a1_backward.md`, `a1_merge.md` |
| `tests/` | Offline tests (injected transport, no network) |
