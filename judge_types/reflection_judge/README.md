# judge_types/reflection_judge/

The ATLAS Reflection Judge — a multi-stage trace-analysis judge that
identifies failure points, builds a backward-grounded causal graph
between them, and only AFTER that assigns taxonomy codes. Ported from
GEPA's `ATLAS_Taxonomy/atlas_reflection_judge/`, stripped of litellm /
Bedrock-default coupling.

Used by `atlas_runtime/reflection_refinement.py` as the end-of-generation
validation gate (replaces the legacy `taxonomy_check` Selection-Judge gate).

## Programs

| File | Purpose |
|---|---|
| [`__init__.py`](__init__.py) | Exports `AtlasReflectionJudge`, `validate_output`, `derive_selection_summary` |
| [`judge.py`](judge.py) | `AtlasReflectionJudge`: orchestrates two-call mode (analysis → mapping → deterministic summary) and single-call mode; one-shot retry on validation failure |
| [`prompts.py`](prompts.py) | LLM prompts: `ANALYSIS_SYSTEM` (Stage 1-7, no taxonomy), `MAPPING_SYSTEM` (Stage 8), `SINGLE_CALL_SYSTEM`, plus user-prompt builders and a retry prompt |
| [`schema.py`](schema.py) | `validate_output` + the enumerated values each output field may take (causal roles, recovery statuses, severities, etc.) |
| [`selection.py`](selection.py) | `derive_selection_summary` — pure-Python compression of the rich diagnostic graph into the selection-oriented buckets (root / candidate-attributable / unrecovered / etc.) |
| [`_llm.py`](_llm.py) | LLM transport bridge: adapts atlas_skill's `learning_calls.support_model_call` to the `LLMCall` signature the judge expects. Surfaces parse failures + truncation diagnostics in a `warnings` list |
