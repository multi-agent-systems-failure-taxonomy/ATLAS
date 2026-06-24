# vendor/atlas/traces/

Trace loading + normalization + behavioral signal extraction for the
ATLAS pipeline. Accepts multiple input formats (tau-bench, KIRA, Codex
sessions, event logs, conversation/Forgecode, plain text, and the already-
unified ATLAS shape) and converts everything to the canonical
`UnifiedTrace` schema before generation or classification.

## Programs

| File | Purpose |
|---|---|
| [`__init__.py`](__init__.py) | Public API: `load_traces`, `normalize_trace`, `extract_signals` |
| [`loader.py`](loader.py) | `TraceLoader` — file/dir/iterable loader with format auto-detection |
| [`normalizer.py`](normalizer.py) | Per-format converters that map raw traces into the unified ATLAS schema |
| [`signals.py`](signals.py) | LLM-free behavioral signal extraction: truncation, looping, refusal, tool-failure patterns |
