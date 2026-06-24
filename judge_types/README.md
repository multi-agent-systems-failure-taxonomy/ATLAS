# judge_types/

Seven taxonomy-aware judges atlas_skill exposes (or stubs for future
implementation). Each judge consumes a taxonomy and produces a different
structured signal.

| # | Judge | Status | File | Purpose |
|---|---|---|---|---|
| 1 | Selection | placeholder | [`selection_judge.py`](selection_judge.py) | trace + taxonomy → flat failure-mode labels (shallow, scalable; for selection/comparison) |
| 2 | Reflection | **real** | [`reflection_judge/`](reflection_judge/) | trace + taxonomy → failure-point causal graph + taxonomy mappings (deep; for mutation/repair) |
| 3 | Mapping | placeholder | [`mapping_judge.py`](mapping_judge.py) | failure_point + taxonomy → best code(s) (modular sub-judge) |
| 4 | Coverage | placeholder | [`coverage_judge.py`](coverage_judge.py) | trace/failure_point + taxonomy → covered / partially / missing (drives expansion) |
| 5 | Quality | placeholder | [`quality_judge.py`](quality_judge.py) | taxonomy + support traces → codebook quality feedback (evaluates codes, not traces) |
| 6 | Calibration | placeholder | [`calibration_judge.py`](calibration_judge.py) | annotation + evidence + taxonomy → reliability of a code assignment (audits Selection) |
| 7 | Selection-Summary | **real** | [`selection_summary_judge.py`](selection_summary_judge.py) | labeled failures → compressed selection signal (root/attributable/unrecovered/terminal/actionable/external buckets) |

## Real implementations

- **Reflection Judge** is ported from GEPA's
  `ATLAS_Taxonomy/atlas_reflection_judge/`, stripped of litellm/Bedrock-default
  coupling. The LLM transport routes through atlas_skill's existing
  `atlas_runtime/learning_calls.py` (Anthropic + OpenAI + Gemini, env-driven).
- **Selection-Summary Judge** wraps the deterministic
  `derive_selection_summary` function inside `reflection_judge/selection.py`.

The Reflection Judge is also the validation gate used by
`atlas_runtime/reflection_refinement.py` at end of generation — it replaces
the legacy `taxonomy_check` Selection-Judge acceptance gate that used to
sit there.

## Placeholders

Each placeholder file declares the judge's intended input/output shapes and
raises `NotImplementedError` from its primary method. Their docstrings define
the contract a future implementation should honor.

Selection Judge is currently a placeholder because the legacy
`atlas_runtime/taxonomy_check.py` (which doubled as the generation gate) has
been removed in favor of the Reflection Judge + refiner. A standalone
shallow per-trace classifier has not yet been ported; GEPA's
`ATLAS_Taxonomy/judge.py::TaxonomyJudge.classify_trace` is the closest
reference target.

## Sequence in a generation+refinement run

```
Reflection Judge  → per-trace deep analysis (causal graph + mappings)
                    drives end-of-generation refinement (add / edit / split / retire)
Selection-Summary → compressed signal derived from Reflection output
Quality Judge     → periodic codebook self-evaluation       (future)
Coverage Judge    → detect missing codes from new traces    (future)
Mapping Judge     → standalone failure-point → code         (future)
Selection Judge   → standalone shallow classifier           (future)
Calibration Judge → audit reliability of Selection output   (future)
```
