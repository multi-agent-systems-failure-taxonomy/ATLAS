# atlas_integration/

Harness-specific skins on top of the harness-neutral
[`atlas_runtime/`](../atlas_runtime/). Each sub-folder adapts the runtime to
one host environment: it owns the event shape, configuration surface, and
transport details that particular host needs.

## Sub-folders

- [`claude_code/`](claude_code/) — Project-local Claude Code integration:
  hook registration, dispatcher routing, transcript handling, and per-session
  state.

- [`codex/`](codex/) — Project-local Codex hook integration: writes
  `.codex/hooks.json`, dispatches Codex lifecycle events into ATLAS, and can
  optionally install a Codex skill guidance package.

- [`single_llm/`](single_llm/) — No-harness integration: drives a single LLM
  conversation through ATLAS's lifecycle without depending on any agent
  framework. Useful for scripts, notebooks, smoke tests, and as a reference
  adapter.

Shared reflection parsing, checkpoint prompts, final-gate validation, runtime
evidence, dashboard data, and taxonomy learning live in `atlas_runtime/`.

## Programs

- [`__init__.py`](__init__.py) — Package marker exporting the integrations.
