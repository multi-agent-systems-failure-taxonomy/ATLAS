# tests/

Unit + integration tests for the atlas_skill package. Run the suite with
`python -m pytest tests/` from the repo root. Tests use hand-crafted
fixtures (under [`fixtures/`](fixtures/)) — no live LLM calls.

## Test files

| File | Covers |
|---|---|
| [`__init__.py`](__init__.py) | Test-package marker + shared defaults |
| [`test_claude_code_integration.py`](test_claude_code_integration.py) | Claude Code runtime skin: hooks, install/uninstall, config round-trip, transcript handling |
| [`test_cli.py`](test_cli.py) | `atlas-find` CLI: stdout/exit-code wiring for inherit-by-id, explicit picker, deprecated bare-picker, and missing-id errors |
| [`test_config.py`](test_config.py) | Shared `atlas.json` config loading, validation, precedence, and CLI wiring |
| [`test_dashboard.py`](test_dashboard.py) | Persistent live taxonomy dashboard (HTTP server, refresh, stop semantics) |
| [`test_doctor.py`](test_doctor.py) | `atlas-doctor` health checks for storage, model recognition, JSON output, and error status |
| [`test_generation_lifecycle.py`](test_generation_lifecycle.py) | MAST → generated-taxonomy lifecycle: warm-up threshold, blocking vs background, rejection paths |
| [`test_import_generation.py`](test_import_generation.py) | `atlas-import-traces` flow: trace loading, refinement-based registration, atomic rollback on failure |
| [`test_judge_types.py`](test_judge_types.py) | `judge_types/` registry, natural-language simple-judge asset loading, selection-summary bucket completeness, Reflection Judge construction |
| [`test_learning_calls.py`](test_learning_calls.py) | LLM-transport boundaries (Anthropic / OpenAI / Gemini), JSON repair-retry, prompt formatters |
| [`test_lifecycle.py`](test_lifecycle.py) | Agent- and model-agnostic lifecycle (start/record/pre_submission/end), idempotency, error paths |
| [`test_mast.py`](test_mast.py) | Built-in MAST floor: 14 known modes, category mapping, fixture-immutability |
| [`test_protocol.py`](test_protocol.py) | Pre-submission gate: reflection shape validation + repair-retry envelope |
| [`test_refinement_lifecycle.py`](test_refinement_lifecycle.py) | Program-local refinement counters + global taxonomy lineage successor links |
| [`test_redaction.py`](test_redaction.py) | Public trace redaction helpers for common secrets and project-specific patterns |
| [`test_repository.py`](test_repository.py) | Display-only repository metadata discovery (git remote, repo name) |
| [`test_resolver.py`](test_resolver.py) | Resolver: three `--inherit` behaviors plus none-selection |
| [`test_runtime_options.py`](test_runtime_options.py) | Reusable runtime CLI options (`RuntimeOptions`, `parse_runtime_args`) |
| [`test_single_llm_integration.py`](test_single_llm_integration.py) | Single-LLM no-harness runtime (drives a stubbed model through the lifecycle) |
| [`test_skip_judge.py`](test_skip_judge.py) | `--skip-judge` flag plumbing: defaults, override path, refinement bypass, session round-trip |
| [`test_store.py`](test_store.py) | Flat taxonomy store: register / fetch_by_id / list_all / unregister, schema validation, atomic writes |
| [`test_taxonomy_data.py`](test_taxonomy_data.py) | Taxonomy data-model helpers: round-trips, mutations, retirement bookkeeping |
| [`test_traces.py`](test_traces.py) | Generation-trace storage + retention reports |
| [`test_traces_cli.py`](test_traces_cli.py) | `atlas-traces` status/export/prune behavior, including dry-run pruning |
| [`test_webview.py`](test_webview.py) | Webview HTTP server: table rendering, detail view, choice recording (no browser needed) |

## Sub-folders

- [`fixtures/`](fixtures/) — Shared test fixtures: a real ATLAS generation
  trace, real ATLAS generation output, and the example taxonomies
  (`tax-django-orm-001` etc.) used by store/resolver/webview tests.
