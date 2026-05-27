# ATLAS Examples

These scripts demonstrate the common ways to use ATLAS.

## Setup

```bash
pip install -e ..               # from the ATLAS repo root
export OPENAI_API_KEY=sk-...    # or use ANTHROPIC_API_KEY + a claude-* model
```

To use an alternative OpenAI-compatible endpoint (Gemini shim, vLLM, etc):

```bash
export OPENAI_BASE_URL=https://your-endpoint.example.com/v1
export OPENAI_MODEL=your-model-id
```

## Scripts

- **basic_usage.py** — generate a taxonomy end-to-end from a trace file.
- **classify_example.py** — classify a new trace against an existing taxonomy.
- **programmatic_usage.py** — fine-grained control via `TaxonomyPipeline` + `SignalExtractor` directly.
- **sample_traces.jsonl** — five tiny synthetic traces you can use to smoke-test the pipeline.
- **sample_taxonomy.json** — the taxonomy produced by running ATLAS on `sample_traces.jsonl`. Use this with `classify_example.py` if you want to try the classifier without generating a fresh taxonomy first.
- **mast_data_taxonomies/** — ready-made taxonomies generated on traces from a variety of public multi-agent systems and benchmarks (see the README inside that directory).

## Quick tests

Generate a taxonomy from the sample traces:

```bash
python basic_usage.py sample_traces.jsonl ./out
```

Or classify a trace using the pre-built sample taxonomy:

```bash
python classify_example.py sample_taxonomy.json sample_traces.jsonl
```

End-to-end taxonomy generation takes roughly 5–15 minutes depending on the trace count and the LLM you point it at.
