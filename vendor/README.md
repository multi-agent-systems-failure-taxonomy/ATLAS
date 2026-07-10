# vendor/

Third-party code vendored into the atlas_skill package so the skill is
self-contained (`pip install atlas-skill` brings everything needed, no
sibling-repo `sys.path` tricks).

## Sub-folders

- [`atlas/`](atlas/) — A snapshot of the upstream ATLAS taxonomy-induction
  library (`multi-agent-systems-failure-taxonomy/ATLAS`). The 8-step
  generation pipeline, the classifier, the trace loader/normalizer, the
  LLM client. Used by `atlas_runtime/generation.py::_atlas_generate` and
  by `atlas_runtime/import_generation.py`.

## Programs

- [`__init__.py`](__init__.py) — Package marker.

## Maintenance

`vendor/atlas/` is a snapshot, not a submodule. To refresh from upstream,
re-clone the upstream repo and overwrite the contents of `vendor/atlas/`
preserving the `LICENSE` and `VENDORED.md` markers. Re-run the full test
suite afterwards — the vendored `PipelineConfig` shape is what
`atlas_runtime/generation.py` adapts to, and changes there may require
matching changes in the adapter (see `_atlas_generate`).
