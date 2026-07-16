# `adamast_integration/interactive/`

Shared conversation infrastructure for the Codex and Claude Code adapters.
This package contains behavior that is independent of either host's hook JSON
or transcript format.

## Runtime contract

One completed assistant episode becomes one trace. A project and task group
share the active taxonomy. A conversation may choose the shared taxonomy,
disable AdaMAST, or start from MAST in a durable isolated `fresh-*` group.
The first resolved program scope is pinned to the conversation identity, so a
later host `cwd` change or resumed shell cannot reopen taxonomy selection.
The original selector choice remains lineage metadata. After generation or
refinement activates a successor, host context names that active taxonomy and
directs checkpoints to its codes without erasing the seed selection.
Codex host-maintenance tasks rooted in `~/.codex/memories` are excluded before
project routing, so user-level hooks do not create selectors for internal work.
Both hosts recover exact legacy inline choices after the saved selector cursor
before deciding that a pending conversation needs the browser again.

When a generation or refinement threshold is reached, the coordinator freezes
eligible evidence and queues one job. The active host first launches a native
taxonomy generator. After deterministic structure and exact-quote checks, a
separate native support reviewer evaluates every replacement code. Only
foreground hook reconciliation can activate a candidate after both receipts.

## Files

| File | Purpose |
|---|---|
| [`selector.py`](selector.py) | Builds, renders, and parses MAST, stored-taxonomy, browser, and AdaMAST-off choices. |
| [`browser_picker.py`](browser_picker.py) | Host-neutral localhost server transport and direct choice application. |
| [`session_routes.py`](session_routes.py) | Durable conversation-to-program bindings and fresh-MAST task-group routes. |
| [`learning_jobs.py`](learning_jobs.py) | Frozen snapshots, polling, job state, validation, notices, and atomic activation. |
| [`subagent_protocol.py`](subagent_protocol.py) | Claim leases, signed receipt envelopes, transcript extraction, and proposal completion. |
| [`worker_contract.py`](worker_contract.py) | Outcome-blind taxonomy prompt and strict candidate JSON schema. |
| [`defaults.py`](defaults.py) | Shared interactive paths and placeholder model defaults. |

The host packages retain facade modules such as
`adamast_integration.codex.browser_picker` so existing imports remain stable.
New host-neutral behavior belongs here; host event parsing belongs in the
corresponding adapter.

See [Native taxonomy learning](../../docs/NATIVE_LEARNING.md) for the persisted
state machine and security boundary.
