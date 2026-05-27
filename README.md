# ATLAS

**Automatic Taxonomy Learning for Agent Systems.**

ATLAS induces a compact, evidence-grounded failure taxonomy from an agent
system's own execution traces — no human annotation required — and then
classifies new traces against it. The induced codes are designed to be
consumed by agent-improvement procedures (search, runtime reflection,
trajectory selection) as a structured feedback interface.

Codes are organized along three fixed axes; the codes themselves are
induced per system:

| Axis | Scope | Examples |
| --- | --- | --- |
| **A** | System-level (any agent) | `Context_Exhaustion`, `Output_Truncation`, `Inter_Agent_Information_Loss` |
| **B** | Role-specific | `Solver_Wrong_Approach`, `Checker_False_Acceptance`, `Refiner_Regression` |
| **C** | Domain-specific | `Sign_Error_In_Algebra`, `Quantifier_Confusion`, `Off_By_One` |

The pipeline infers the system's architecture, roles, capabilities, and
task domain from the traces themselves.

## Install

```bash
git clone https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git
cd ATLAS
pip install -e .
```

Set one API key:

```bash
export OPENAI_API_KEY=sk-...                            # OpenAI (default)
export OPENAI_BASE_URL=...                              # any OpenAI-compatible endpoint
export ANTHROPIC_API_KEY=...  ATLAS_MODEL=claude-haiku-4-7
```

## Generate a taxonomy

CLI:

```bash
python -m atlas generate --traces my_traces.jsonl --output ./out
```

Python:

```python
from atlas import generate_taxonomy

taxonomy = generate_taxonomy(
    traces="my_traces.jsonl",   # file, directory, or list of dicts
    output_dir="./out",
    max_codes=25,               # optional; 0 = no cap
)
```

The taxonomy is written to `./out/taxonomy.json`. Per-stage intermediate
files (`step1_domain_info.json` … `step8_final.json`) are written
alongside it so you can inspect what each stage produced.

## Classify a trace

```python
from atlas import classify_trace, load_traces

trace = load_traces("new_failure.json", verbose=False)[0]
diagnosis = classify_trace("./out/taxonomy.json", trace)
print(diagnosis.code, diagnosis.label, diagnosis.evidence)
```

Or:

```bash
python -m atlas classify --taxonomy ./out/taxonomy.json --trace new.json
```

## Trace formats

The loader auto-detects:

| Format | Detection |
| --- | --- |
| ATLAS unified | `raw_trajectory` field |
| tau-bench | `traj` + `task_id` + `reward` |
| Codex CLI session | `type: session_meta/response_item/...` in JSONL |
| Event log | `event` field per JSONL entry |
| Conversation / Forgecode | `messages` list of role/content dicts |
| KIRA trajectory | step dicts with `step_id` + `tool_calls` |
| Plain text | any string |

Mix formats freely; point the loader at a directory and it picks the
right converter per file. For a custom shape, normalize once yourself:

```python
from atlas import normalize_traces, generate_taxonomy

traces = [t.to_dict() for t in normalize_traces(my_records)]
taxonomy = generate_taxonomy(traces, output_dir="./out")
```

## Output

`taxonomy.json` has two layers:

- **`annotation_layer`** — `code`, `name`, `definition`, `severity`. Pass
  this to an LLM judge that classifies traces.
- **`full_layer`** — adds `when_to_use`, `when_not_to_use`,
  `detection_heuristics`, discovered architecture, roles, signals. Use
  this when iterating on the taxonomy.

```jsonc
{
  "metadata": {
    "version": "1.0.0",
    "traces_analyzed": 38,
    "counts": { "category_a": 6, "category_b": 7, "category_c": 14, "total": 27 }
  },
  "category_definitions": {
    "A": "System-level failures (agent-independent).",
    "B": "Role-specific quality failures.",
    "C": "Domain-specific reasoning failures."
  },
  "role_definitions": { "solver": {...}, "checker": {...} },
  "annotation_layer": { "category_a": [...], "category_b": [...], "category_c": [...] },
  "full_layer":       { /* heuristics, signals, architecture, domain_info */ }
}
```

## Pipeline

Eight stages, intermediate JSON saved after each:

1. **Domain analysis** — task type, terminology, characteristic error patterns.
2. **Structure extraction** — agents, roles, topology, trace format.
3. **Signal extraction** — LLM-free behavioral checks (truncation,
   looping, refusal, tool errors).
4. **A-code generation** — architectural risk analysis + observed signals.
5. **B-code generation** — per-role quality failure modes.
6. **C-code generation** — domain-seeded + trace-grounded reasoning errors.
7. **Cross-category dedup** — concepts that landed in two axes.
8. **Check + fix** — naming rules, coverage gaps, overlap merges.

## Configuration

| Env var | Default | Use |
| --- | --- | --- |
| `ATLAS_MODEL` | OpenAI default | LLM model id |
| `ATLAS_TIMEOUT` | `180` | per-call timeout (s) |
| `ATLAS_MAX_CODES` | `0` | cap on total codes; `0` = no cap |
| `OPENAI_API_KEY` | — | required for OpenAI / compatible |
| `OPENAI_BASE_URL` | — | alternative OpenAI-compatible endpoint |
| `ANTHROPIC_API_KEY` | — | required when `ATLAS_MODEL` starts with `claude` |

```python
from atlas import PipelineConfig, TaxonomyPipeline

config = PipelineConfig(model="claude-haiku-4-7", max_codes=20, save_intermediate_steps=False)
taxonomy = TaxonomyPipeline(config=config, output_dir="./out").run(traces)
```

## Example taxonomies

`examples/mast_data_taxonomies/` contains taxonomies pre-generated on
traces from [MAST-Data](https://huggingface.co/datasets/mcemri/MAST-Data),
one per (multi-agent system, benchmark) combination — AG2-MathChat,
ChatDev, MetaGPT, AppWorld, HyperAgent, Magentic-One, OpenManus. Drop-in
usable with `classify_trace`.

A smaller `examples/sample_taxonomy.json` (generated from
`examples/sample_traces.jsonl`) is included for smoke-testing without
running the full pipeline.

## Layout

```
atlas/
├── api.py            # generate_taxonomy, classify_trace, classify_traces
├── cli.py            # python -m atlas
├── classifier.py     # TaxonomyClassifier, Diagnosis
├── config.py         # PipelineConfig
├── llm.py            # OpenAI/Anthropic wrapper + JSON extraction
├── utils.py
├── traces/
│   ├── loader.py     # file/dir/iterable loader, auto-detection
│   ├── normalizer.py # per-format converters
│   └── signals.py    # LLM-free behavioral signals
└── pipeline/
    ├── pipeline.py   # eight-step orchestrator
    ├── prompts.py
    ├── domain.py     # step 1
    ├── structure.py  # step 2
    ├── generator.py  # steps 3–5
    ├── dedup.py      # step 6
    ├── validate.py   # step 7
    └── check.py      # step 8
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Covers trace loading, normalization across formats, and the LLM-free
signal extractor. The full pipeline is exercised via the example
scripts (which require an API key).

## Citation

```
@article{atlas2026,
  title={Adaptive Failure Taxonomies as Feedback for LLM-Agent Improvement Procedures},
  author={Cemri, Mert and Cojocaru, Andrei and Pan, Melissa and Liu, Shu and
          Agarwal, Shubham and Krentsel, Alexander and Tang, Jay and
          Ramchandran, Kannan and Gonzalez, Joseph E. and Zaharia, Matei and
          Dimakis, Alex and Stoica, Ion},
  year={2026}
}
```

## License

Apache 2.0.
