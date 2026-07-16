# `adamast_integration/`

Host adapters for the harness-neutral [`adamast_runtime/`](../adamast_runtime/).
Each adapter translates one host's events and transcript format into the same
session, gate, trace, and learning contracts.

## Choose an adapter

| Folder | Use it for | Primary entry point |
|---|---|---|
| [`codex/`](codex/) | Codex app and CLI conversations | `adamast-codex-install` |
| [`claude_code/`](claude_code/) | Claude Code conversations | `adamast-claude-install` |
| [`single_llm/`](single_llm/) | Scripts, notebooks, and one direct model call | `adamast-single-run` |
| [`interactive/`](interactive/) | Shared infrastructure used by Codex and Claude Code | Internal library |

Codex and Claude Code keep thin host facades for stable imports. Taxonomy
selection, browser transport, fresh-conversation routing, durable learning
jobs, candidate schemas, and receipt validation live in
[`interactive/`](interactive/), where both hosts exercise the same behavior.

## Ownership boundary

```text
host hook JSON
    -> codex/ or claude_code/       event and transcript translation
    -> interactive/                selector, routes, jobs, receipts
    -> adamast_runtime/               sessions, gates, traces, activation
    -> finding/                     taxonomy store and local browser UI
```

Host adapters may decide *when* an event fires and *how* a host receives
context. They must not independently implement taxonomy validation or
activation. Those remain runtime-owned so all integrations preserve the same
lineage and evidence rules.

See [Architecture](../docs/ARCHITECTURE.md) for the complete repository map and
[Native taxonomy learning](../docs/NATIVE_LEARNING.md) for the interactive job
protocol.

## Files

| File | Purpose |
|---|---|
| [`shared.py`](shared.py) | Small state and UTF-8 helpers shared across adapters. |
| [`__init__.py`](__init__.py) | Package marker for integration modules. |
