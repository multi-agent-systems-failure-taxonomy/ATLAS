# atlas_skill

A fresh, general-purpose ATLAS implementation — agent- and model-agnostic. It
is a framework, driven entirely through a Python runtime API, so any agent
runtime or model provider can use it without ATLAS knowing anything about them.
Current scope:

- Taxonomy Finding and the built-in MAST floor.
- Program identity through mandatory `--trace-output`.
- A minimal pre-submission gate with bounded repair retries.
- Program-scoped trace persistence.
- Initial MAST-to-generated-taxonomy transition at N traces.
- Program-local refinement cadence with globally shared taxonomy successors.
- Basic structural refinement plus optional one-shot judge-guided repair.
- Persistent live localhost taxonomy dashboard.
- Validated flat taxonomy registration.
- Claude Code blocking checkpoint integration.
- Single-model, no-harness checkpoint integration.

The engine remains harness-neutral. Supported runtime skins currently include
Claude Code and direct single-model conversations. Other frameworks can drive
the public API (`start_session` / `record_trace` / `pre_submission` /
`end_session`) directly.

## Install

Python 3.10 or newer is required.

Install directly from the release branch:

```sh
python -m pip install "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"
```

Or from a local checkout:

```sh
python -m pip install .
```

Anthropic-backed task or learning calls additionally require:

```sh
python -m pip install ".[anthropic]"
```

The package installs `atlas-find`, `atlas-dashboard`,
`atlas-import-traces`, `atlas-claude-install`, `atlas-claude-uninstall`, and
`atlas-single-run`.

Taxonomy selection follows the same three forms across supported CLIs:

- omit `--inherit` to begin with MAST;
- pass `--inherit <taxonomy_id>` to select a stored taxonomy;
- pass `--inherit` without a value to open the local taxonomy picker.

OpenAI-compatible calls use `OPENAI_API_KEY` and optional
`OPENAI_BASE_URL`. Anthropic calls use the credential environment variables
recognized by the Anthropic SDK. Gemini learning calls use `GEMINI_API_KEY`
or `GOOGLE_API_KEY`. Credentials are never written into ATLAS configuration.

The static [SKILL.md](SKILL.md) contains only standing interaction behavior.
It deliberately does not embed the active taxonomy; runtime integrations
surface taxonomy codes only when a checkpoint fires.

## Claude Code

Install project-local hooks after installing the package:

```powershell
atlas-claude-install `
  --project-dir C:\path\to\project `
  --trace-output C:\path\to\atlas-program `
  --atlas-model gpt-5
```

The hook command invokes the installed Python module, so moving or deleting
the source checkout does not break registration. To remove the integration:

```powershell
atlas-claude-uninstall --project-dir C:\path\to\project
```

Users upgrading from the old global `atlas-failure-modes` installation can
remove its global hook registrations during install:

```powershell
atlas-claude-install ... --migrate-legacy-global
```

This migration preserves unrelated Claude settings and does not delete the
legacy skill directory.

Claude Code discovery checks `CLAUDE_CODE_EXECUTABLE`, then `claude` on
`PATH`, followed by common Windows, macOS, and Linux installation locations.
Set `CLAUDE_CODE_EXECUTABLE` when using a custom installation. Installation
still verifies every required hook event and blocking contract against the
discovered version before registering anything.

For an OpenAI-compatible learning endpoint, pass the endpoint and the name of
an inherited credential variable:

```powershell
$env:ATLAS_LEARNING_KEY = "..."
atlas-claude-install ... `
  --openai-base-url http://127.0.0.1:8742/v1 `
  --openai-api-key-env ATLAS_LEARNING_KEY
```

Only `ATLAS_LEARNING_KEY` is stored; its value remains in the process
environment.

Claude installation exposes the engine lifecycle controls:

```text
--generation-threshold N
--generation-stops / --no-generation-stops
--taxonomy-check / --no-taxonomy-check
--k-init N
--k N
--refinement-stops / --no-refinement-stops
--advanced-refinement / --no-advanced-refinement
--failure-throttle-calls N
--failure-recency-seconds N
```

## Single-model calls without a harness

Use the callback API when an application already owns model transport:

```python
from atlas_integration.single_llm import SingleLLMConfig, run_single_llm

result = run_single_llm(
    "Solve the task.",
    my_message_callback,
    SingleLLMConfig(
        trace_output="run/program",
        trace_root="run/traces",
        atlas_model="gpt-5",
    ),
)
print(result.answer)
```

The callback receives a list of `{role, content}` messages and returns the next
assistant text. The adapter pauses on explicit major-segment checkpoint
requests, injects the taxonomy at that boundary, records firing evidence,
enforces the final gate, captures the conversation trace, and invokes the
normal generation/refinement lifecycle.

For OpenAI-compatible or Anthropic-backed direct execution:

```powershell
atlas-single-run `
  --task "Solve the task" `
  --model gpt-5 `
  --trace-output C:\path\to\atlas-program
```

`atlas-single-run` reads provider credentials from the environment and never
accepts a credential value as a command-line argument.

## Taxonomy model

Taxonomies are first-class records identified only by `taxonomy_id`:

```json
{
  "taxonomy_id": "example-id",
  "repo": "display only",
  "domain": "display only",
  "codes": []
}
```

`repo` and `domain` route nothing. By default, stored records live at
`~/.atlas-skill/taxonomies/<taxonomy_id>.json` and learning traces at
`~/.atlas-skill/traces/<taxonomy_id>/`. Override the shared root with
`ATLAS_HOME`, or each location with `ATLAS_STORE_DIR` and
`ATLAS_TRACE_ROOT`. Explicit CLI/API paths always win. MAST is a built-in
constant, not a store record and not a picker row.

For generated taxonomies, `domain` is copied from the standard ATLAS
eight-stage pipeline's Step 1 domain analysis
(`full_layer.domain_info.domain.name`). `repo` is copied from persisted program
metadata, supplied explicitly or derived from the checkout. Both fields remain
display-only.

## Live taxonomy dashboard

The runtime now starts a read-only dashboard automatically with the first
active task in a program. Concurrent tasks reuse the same dashboard URL. It
stops after the final task once no generation or refinement job is still
running. The calling agent or framework can surface
`SessionDelivery.dashboard_url` to users.

The dashboard can still be run manually:

```sh
python -m atlas_runtime.dashboard \
  --trace-output <program-specific-directory> \
  --store-dir taxonomies
```

It opens at `http://127.0.0.1:8765/` by default and stays live until stopped.
Use `--port 0` to request any available port, or `--no-browser` to avoid
opening a tab automatically.

The page polls the program state every 1.5 seconds. It renders MAST before a
taxonomy is bound, then always resolves and displays the latest successor of
the program's current taxonomy without a server restart. Users can filter,
expand, and collapse code definitions. Real taxonomies show per-code firing
counts and unique task IDs only when that evidence is present.

To preview that future evidence layout with disposable placeholder data:

```sh
python -m examples.dashboard_demo
```

The demo shows total firings and unique task IDs with a per-task count for
five fictional failure modes. Its temporary program and taxonomy store are
deleted when you stop it with `Ctrl+C`; it does not modify the real store.

## Required program identity

Every runtime invocation must provide:

```sh
--trace-output <program-specific-directory>
--atlas-model <recognized-model-id>
```

`--trace_output` is accepted as an alias. Repository metadata can be supplied
with `--repo owner/project` or derived from `--repo-path <checkout>`. Without
either, ATLAS derives it from the current git checkout. This value is persisted
once per program and remains display-only.

First use creates:

```text
<trace-output>/
├── .atlas-program.json
└── pending/
```

The manifest contains a stable `program_id` and display-only `repo`. Reusing the same trace-output
directory means the same program across tasks and process invocations. A
different directory creates a different program.

The reusable parser in `atlas_runtime.options` also exposes:

```sh
--generation-stops       # default: false
--no-generation-stops
--refinement-stops       # default: false
--no-refinement-stops
--advanced-refinement    # default: false
--no-advanced-refinement
--taxonomy-check         # default: true
--no-taxonomy-check
```

`--atlas_model`, `--taxonomy_check`, `--refinement_stops`, and
`--advanced_refinement` are accepted as underscore aliases. The selected
ATLAS model is stored on the program and is shared by taxonomy generation,
the external taxonomy judge, and refinement. Its context limit is resolved
internally; users do not specify token limits.

## Session selection

At task start:

- An explicitly inherited taxonomy is validated and bound to the program.
- A program already bound to a taxonomy automatically reuses it.
- A program with no taxonomy uses built-in MAST.
- Asking an already-bound program to use a different taxonomy is an error.

The selected taxonomy is immutable for that task. A generated taxonomy never
replaces the taxonomy of an already-running task.

## Trace format and placement

Every trace is the canonical four-field record accepted by
`atlas.generate_taxonomy`:

```json
{
  "problem_id": "stable task/attempt id",
  "task": "task prompt or objective",
  "raw_trajectory": "plain-text execution trajectory",
  "metadata": {}
}
```

At task completion, each trace is atomically written as an independent JSON
file under `<trace-output>/pending/`.

For an inherited/approved taxonomy:

```text
pending/
→ copy into traces/<taxonomy_id>/
→ verify destination bytes
→ remove pending source
```

If integration fails, the pending source remains available for recovery.

## Generate an inheritable taxonomy from user traces

A user can run the upstream ATLAS loader and full eight-stage generation
pipeline immediately on an existing trace file or directory, without creating
or binding an ATLAS program:

```powershell
python -m atlas_runtime.import_generation `
  --traces C:\path\to\trace-file-or-directory `
  --atlas-model gpt-5 `
  --store-dir C:\path\to\taxonomies `
  --trace-root C:\path\to\learning-traces `
  --repo my-project
```

The import command auto-detects canonical ATLAS, JSON/JSONL, tau-bench,
Codex sessions, event logs, conversation/Forgecode records, KIRA trajectories,
and a directly supplied plain-text trajectory file. Directories are scanned
recursively for JSON and JSONL files, matching the upstream loader.

This path bypasses the runtime `N=5` trigger, but otherwise preserves the
normal acceptance guarantees:

1. Normalize every usable input to the canonical four-field trace schema.
2. Run the upstream eight-stage taxonomy generator.
3. Run the existing support-based taxonomy check by default.
4. Allocate a taxonomy ID only after acceptance.
5. Transactionally register `<store-dir>/<taxonomy_id>.json`.
6. Store the imported traces under `<trace-root>/<taxonomy_id>/`.
7. Preserve generation/check artifacts under
   `<store-dir>/_state/imports/<taxonomy_id>/`.

The imported taxonomy is dormant: it is not attached to any program until
selected with `--inherit <taxonomy_id>`. Rejected or invalid imports create no
taxonomy record or taxonomy trace folder. `--no-taxonomy-check` is available
for deliberate structural-only acceptance.

## Initial MAST generation lifecycle

Default threshold: **N = 5** pending traces from the same program. Successful
and failing task traces count equally; outcome is not part of the stored
generation input.

```text
task finishes with MAST
→ trace written to the program's pending folder
→ pending count reaches 5
→ generate a candidate through atlas.generate_taxonomy
```

### Non-blocking generation (default)

With `generation_stops=false`, a detached worker performs generation. Tasks may
continue using MAST while it runs.

When generation finishes, activation waits until the program has no running
tasks. Thus no running task receives a mid-task taxonomy replacement.

### Blocking generation

With `--generation-stops`, the threshold-crossing task waits at its completion
boundary until generation succeeds, fails, or is rejected.

### Acceptance and activation

By default, a generated candidate is checked by an external judge before it
can receive a taxonomy ID. `--no-taxonomy-check` skips this pass and uses
structural acceptance only.

The check freezes the current pending trace set as an immutable filename/hash
snapshot after generation finishes. Traces may continue arriving, but the
running check ignores anything outside its snapshot. If accepted, activation
still integrates every pending trace, including those that arrived during the
check.

Judge batching is adaptive:

- At most 4 trace units per model call.
- The selected model's context window is resolved internally.
- Taxonomy/prompt overhead, output reserve, and a safety margin are subtracted.
- Batches shrink below 4 when necessary.
- A single oversized trace is split into context-safe chunks.
- Chunk findings are unioned back to the original trace.
- A code receives at most one support vote per distinct trace, never per chunk.

The judge assigns only candidate code IDs. Unknown and duplicate assignments
are ignored. A supplied quote must occur in the same chunk. Invalid batch
output receives one repair retry; a failed or omitted unit contributes no
support and cannot crash the pass.

Initial code state:

- Fired in at least one distinct trace: `ACTIVE`, `firing_rounds=1`,
  `zero_strikes=0`, advisory gate force.
- Never fired: `PROVISIONAL`, `firing_rounds=0`, `zero_strikes=1`.

Acceptance requires at least **5 ACTIVE codes**, each observed in at least one
distinct trace. This taxonomy check currently applies only after initial
generation, not after refinement.

Candidates have **no taxonomy_id**. Only after acceptance:

1. Wait for all running tasks in the program to finish.
2. Allocate a unique taxonomy ID.
3. Stage and verify copies of all pending traces.
4. Create `traces/<taxonomy_id>/`.
5. Register `taxonomies/<taxonomy_id>.json`.
6. Atomically bind the program manifest to that taxonomy.
7. Remove verified pending copies.

Generated records keep the Step 1 discovered domain and copy the program's
display-only repository metadata:

```json
{
  "repo": "owner/project",
  "domain": "Software Engineering / Code Repair"
}
```

If generation fails or the candidate is rejected:

- MAST remains active.
- No taxonomy ID is allocated.
- No taxonomy JSON or taxonomy trace folder is created.
- All traces remain in the program pending folder.
- A blocking task is released with a failure/rejection result.
- A later completed MAST task may retry generation.

For a rejected candidate or technical judge failure, the frozen check count
becomes the retry anchor. ATLAS waits for another `N` traces beyond that
snapshot, then regenerates using **all accumulated pending traces**, including
previously judged traces. If at least `N` traces arrived while generation or
checking was running, regeneration begins immediately. Overshooting the
threshold is allowed.

## Refinement lifecycle

Refinement cadence belongs to the program, while taxonomy succession is shared
globally:

```text
program counter: local to <trace-output>
taxonomy link:   old taxonomy_id -> refined taxonomy_id
```

Defaults:

- `K_init = 10`: completed traces after a program first begins using a
  taxonomy, up to that program's first refinement.
- `K = 20`: completed traces after each successful refinement performed by
  that program.

For an inherited taxonomy, counting starts at zero. For a taxonomy generated
from MAST, the five warm-up traces do not count: counting starts with the first
task that actually receives the generated taxonomy.

Each completed task using a non-MAST taxonomy:

1. Writes its trace to pending.
2. Integrates it into `traces/<taxonomy_id>/`.
3. Adds a program-local reference to that exact trace.
4. Increments `traces_since_refinement`.
5. Triggers at `K_init` before the first successful program refinement, then
   at `K` thereafter.

Successful refinement creates a new taxonomy record and a global successor
link:

```text
T1 -> T2
```

Every accepted refinement also persists a deterministic structural-diff
artifact at:

```text
taxonomies/_state/refinements/<new-taxonomy-id>.json
```

The diff records repo/domain changes plus added, removed, and changed code
identities.

It never overwrites T1. Programs using T1 follow T2 at their next task start.
If another program caused the refinement, the following program preserves its
own `rounds_completed`, trace count, and trace references. Only the program
that successfully publishes a refinement resets its counter.

`--refinement-stops` mirrors generation:

- Default false: start refinement in the background and keep using the current
  taxonomy until the refinement is accepted and no task is running.
- True: the threshold-crossing task waits at completion for refinement.

Rejected or failed refinement keeps the current taxonomy and preserves the
program's full counter and trace set for a later retry. Refined candidates do
not receive a taxonomy ID until acceptance.

Basic refinement is the default:

```text
current taxonomy + frozen program traces
-> refinement model
-> complete replacement candidate
-> structural validation and diff
-> acceptance
```

With `--advanced-refinement`, one support-judge phase is inserted:

```text
candidate + diff + same frozen traces
-> support judge
-> no issues: accept
-> issues: one repair-model call, recompute diff, accept without re-judging
```

This deliberately does not restore the old failure-mode lifecycle: no
ACTIVE/PROVISIONAL mutation, firing rounds, zero strikes, maturity ladder, or
repeated judge/repair loop. Callers may inject refinement, judge, repair, and
approval functions for custom execution; otherwise the configured ATLAS model
is used for the model calls.

## Retention

Trace records never expire automatically. The store reports warnings when:

- a trace folder contains more than 10,000 records; or
- its oldest trace file is more than 90 days old.

Age uses file modification time because timestamps are not yet part of the
approved generation trace schema. Archival/deletion remains future policy.

## Tests

```sh
python -m unittest discover -s tests -t . -v
```

Tests cover mandatory program identity, inherited and MAST starts,
pending-first writes, verified integration, N=5 blocking and background
generation, rejection/failure preservation, no mid-task replacement, taxonomy
registration, retention warnings, and the pre-submission retry gate.
