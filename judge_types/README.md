# judge_types/

Seven taxonomy-aware judges atlas_skill exposes. Each judge consumes a
taxonomy and produces a different structured signal.

| # | Judge | Status | File | Purpose |
|---|---|---|---|---|
| 1 | Selection | **real** | [`selection_judge.py`](selection_judge.py) | trace + taxonomy → flat failure-mode labels (shallow, scalable; for selection/comparison) |
| 2 | Reflection | **real** | [`reflection_judge/`](reflection_judge/) | trace + taxonomy → failure-point causal graph + taxonomy mappings (deep; for mutation/repair) |
| 3 | Mapping | **real** | [`mapping_judge.py`](mapping_judge.py) | failure_point + taxonomy → best code(s) (modular sub-judge) |
| 4 | Coverage | **real** | [`coverage_judge.py`](coverage_judge.py) | trace/failure_point + taxonomy → covered / partially / missing (drives expansion) |
| 5 | Quality | **real** | [`quality_judge.py`](quality_judge.py) | taxonomy + support traces → codebook quality feedback (evaluates codes, not traces) |
| 6 | Calibration | **real** | [`calibration_judge.py`](calibration_judge.py) | annotation + evidence + taxonomy → reliability of a code assignment (audits Selection) |
| 7 | Selection-Summary | **real** | [`selection_summary_judge.py`](selection_summary_judge.py) | labeled failures → compressed selection signal (root/attributable/unrecovered/terminal/actionable/external buckets) |

## Shared shape

Every LLM-based judge (everything except Selection-Summary, which is
deterministic) follows the same shape so they're composable and testable:

- A class (`SelectionJudge`, `MappingJudge`, …) with a required
  `judge_model` constructor argument and an optional `llm_call` injection
  point for tests (matches the `(prompt, model) -> raw_text` signature
  used by `atlas_runtime.learning_calls.support_model_call`).
- A `run(...)` method returning a frozen dataclass result with a
  `judge_metadata` dict (judge name, model, taxonomy version, timestamp,
  warnings collected during the call).
- A module-level `validate_output(data, catalog_codes)` for structural
  + enum validation; the class uses it internally and salvages partial
  output rather than crashing on minor schema misses.
- A module-level `run(...)` convenience function for one-shot use.

All judges route their LLM call through
`atlas_runtime/learning_calls.py::judge_json`, which already handles JSON
repair-retry and routes to Anthropic (incl. Bedrock) / OpenAI / Gemini
based on the model id.

## Real implementations

- **Selection Judge** — shallow per-trace classifier. Replaces the
  workspace-coupled `taxonomy_check.py` we removed; this version is
  standalone, no `ProgramWorkspace` required.
- **Reflection Judge** — ported from GEPA's
  `ATLAS_Taxonomy/atlas_reflection_judge/`, stripped of
  litellm/Bedrock-default coupling.
- **Mapping Judge** — single-failure-point code assignment. Mirrors the
  Reflection Judge's two-call Stage 8 but standalone.
- **Coverage Judge** — given a trace and/or failure point, decides
  whether the taxonomy covers / partially covers / misses the pattern;
  proposes a new code when warranted.
- **Quality Judge** — evaluates the taxonomy itself (codes for
  observability, overlap, scope, clarity). Optional support traces
  ground recommendations in evidence.
- **Calibration Judge** — audits a Selection-Judge annotation against
  the cited evidence; flags weak-evidence/high-confidence mismatches
  and possible over-triggers.
- **Selection-Summary Judge** — deterministic compression of Reflection
  Judge output into root/attributable/unrecovered/etc. buckets.

The Reflection Judge is also the validation gate used by
`atlas_runtime/reflection_refinement.py` at end of generation — it
replaces the legacy `taxonomy_check` Selection-Judge acceptance gate
that used to sit there.

## How each judge fits in a generation+refinement run

```
Selection Judge   → cheap per-trace classification (scoring, statistics, CI)
Reflection Judge  → per-trace deep analysis (causal graph + mappings)
                    drives end-of-generation refinement (add / edit / split / retire)
Mapping Judge     → standalone code assignment for one failure point
Coverage Judge    → fast yes/no on whether the taxonomy covers a new failure
Quality Judge     → periodic codebook self-evaluation
Calibration Judge → audit Selection-Judge annotations for evidence support
Selection-Summary → deterministic compression of Reflection output
```
