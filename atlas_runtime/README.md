# atlas_runtime/

Harness-neutral, agent- and model-agnostic ATLAS runtime engine. Owns the
lifecycle, the generation/refinement transitions, the LLM-call transports,
the persisted program/trace state, and the live dashboard. All harness
integrations (`atlas_integration/claude_code/`, `atlas_integration/single_llm/`)
sit on top of this layer.

## Programs

| File | Purpose |
|---|---|
| [`__init__.py`](__init__.py) | Public API exports for the runtime package |
| [`dashboard.py`](dashboard.py) | Persistent localhost web dashboard showing the program's current taxonomy + live runtime evidence |
| [`generation.py`](generation.py) | MAST → generated-taxonomy transition: trigger, run, refine via reflection judge, register + activate |
| [`import_generation.py`](import_generation.py) | One-shot CLI (`atlas-import-traces`): generate + refine + register a dormant inheritable taxonomy from user-supplied traces |
| [`learning_calls.py`](learning_calls.py) | LLM transport for judge + refiner calls (Anthropic SDK, OpenAI SDK, Gemini REST — chosen by model-id prefix + env vars); JSON repair-retry |
| [`lifecycle.py`](lifecycle.py) | Session/task lifecycle: `start_session`, `record_trace`, `pre_submission`, `end_session`; threads generation + refinement triggers |
| [`lineage.py`](lineage.py) | Global taxonomy successor links (refined → successor id), independent of any program's local refinement counter |
| [`models.py`](models.py) | Recognized model profiles (token budgets, family detection) used for adaptive judge batching |
| [`options.py`](options.py) | Reusable argparse options + `RuntimeOptions` dataclass shared by every harness integration |
| [`program.py`](program.py) | `ProgramWorkspace`: program identity, manifest, pending-trace store, lock-coordinated state transitions |
| [`protocol.py`](protocol.py) | Minimal pre-submission gate: reflection-shape validation + repair-retry envelope |
| [`refinement.py`](refinement.py) | Program-local refinement cadence (K_init / K thresholds) — fires periodically against the active taxonomy |
| [`reflection_refinement.py`](reflection_refinement.py) | End-of-generation validation via the Reflection Judge + LLM refiner — replaces the legacy `taxonomy_check` Selection-Judge gate |
| [`repository.py`](repository.py) | Display-only repository metadata discovery (git remote, repo name) — never used for taxonomy routing |
| [`taxonomy_data.py`](taxonomy_data.py) | Taxonomy data model: `Code`, `Taxonomy`, `JudgeLog`, `CostMeter`, `render_code_spec`. Ported from GEPA |
| [`traces.py`](traces.py) | Crash-safe per-program trace files in the canonical ATLAS generation-input shape; integration across taxonomy successors |

## Two refinement modules — what's the difference?

| | `refinement.py` | `reflection_refinement.py` |
|---|---|---|
| When | Periodic (K-cadence) during normal task flow | One-shot at end of generation |
| Trigger | `end_session` after K_init / K traces accumulate | `_generate_and_refine_once` in `generation.py` |
| Judge | Optional "advanced refinement" support-judge (when `--advanced-refinement`) | Always uses the AtlasReflectionJudge |
| Mutates via | Refiner-produced full-replacement taxonomy | Add / edit / split / retire mutations on a `Taxonomy` object |

Both are real, separate concerns. `refinement.py` is the long-running
program-local cadence; `reflection_refinement.py` is the validation gate
that replaced `taxonomy_check`.
