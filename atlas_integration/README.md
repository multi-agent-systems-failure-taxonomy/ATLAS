# atlas_integration/

Harness-specific skins on top of the harness-neutral [`atlas_runtime/`](../atlas_runtime/).
Each sub-folder adapts the runtime to one host environment: it owns the
event shape, the configuration surface, and the LLM/transport wiring that
particular host needs.

## Sub-folders

- [`claude_code/`](claude_code/) — Project-local Claude Code integration:
  hook registration, the dispatcher that routes every hook event to the
  right runtime checkpoint, transcript handling, and the per-session state
  store. The reflection parser, checkpoint prompt body, and runtime-evidence
  schema live in `atlas_runtime/` so other adapters can share them.

- [`single_llm/`](single_llm/) — No-harness integration: drives a single
  LLM conversation through ATLAS's lifecycle (record trace → pre-submission
  gate → end session) without depending on any agent framework. Useful for
  scripts, notebooks, and as a reference adapter.

## Programs

- [`__init__.py`](__init__.py) — Package marker exporting the two integrations.
