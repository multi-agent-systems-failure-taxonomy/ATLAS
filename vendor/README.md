# vendor/

Third-party code vendored into the AdaMAST package so the skill is
self-contained (`pip install adamast` brings everything needed, no
sibling-repo `sys.path` tricks).

## Sub-folders

- [`adamast/`](adamast/) — A snapshot of the upstream AdaMAST taxonomy-induction
  library (`multi-agent-systems-failure-taxonomy/ATLAS`). The 8-step
  generation pipeline, the classifier, the trace loader/normalizer, the
  LLM client. Used by `adamast_runtime/generation.py::_adamast_generate` and
  by `adamast_runtime/import_generation.py`.

## Programs

- [`__init__.py`](__init__.py) — Package marker.

## Maintenance

`vendor/adamast/` is a snapshot, not a submodule. To refresh from upstream,
re-clone the upstream repo and overwrite the contents of `vendor/adamast/`
preserving the `LICENSE` and `VENDORED.md` markers. Re-run the full test
suite afterwards — the vendored `PipelineConfig` shape is what
`adamast_runtime/generation.py` adapts to, and changes there may require
matching changes in the adapter (see `_adamast_generate`).
