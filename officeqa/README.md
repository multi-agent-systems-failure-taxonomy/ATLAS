# OfficeQA × atlas_skill (Claude Code) runner

Drives the **new** `atlas_skill` Claude Code integration over the OfficeQA benchmark, end
to end, on your Claude Code **login** — no API key anywhere.

- **Task agent** = Claude **Haiku** (headless `claude -p`), one session per question.
- **Learning** (the 8-stage generator, the support judge, and the refiner) = Claude
  **Sonnet**, reached through a tiny OpenAI-shim proxy (`cc_proxy.py`) so it also runs on
  the login. The framework's existing "OpenAI path" is pointed at the proxy; the
  `atlas_model` is set to `gpt-5` purely so that path is taken *and* a token-budget profile
  resolves. The proxy ignores the id and always calls Sonnet.

It only **orchestrates** — it makes zero edits to `atlas_skill`. Everything it produces
lands under `officeqa/run/` (gitignored).

The task-agent invocation uses a compact custom system prompt, only
`Read,Grep,Glob,Bash`, local settings (for the ATLAS hooks), no MCP servers,
no slash commands, no Chrome integration, and low effort. Claude Code's
`--bare` and `--safe-mode` are intentionally not used because they disable
hooks. Per-iteration token/cache usage is logged and stored in `results.jsonl`
so harness overhead can be compared empirically.

The local proxy credential is passed through the inherited
`ATLAS_CC_PROXY_KEY` environment variable. Its value is not persisted in
`.claude/atlas-skill.json`.

## Prerequisites

1. **Claude Code installed and logged in:** `claude /login` (the agent and the learning
   both run on this login).
2. **`pip install openai`** (the framework's learning path imports the OpenAI SDK; it talks
   to the local proxy, not to OpenAI).
3. The OfficeQA corpus present at the default location
   (`olympiad-agents/officeqa/officeqa_corpus/.../transformed` + `officeqa_out/officeqa_pro.csv`).
   Override with `--corpus` / `--questions` if it lives elsewhere.

## Run it

From this folder:

```sh
python run_officeqa_atlas.py --n 20 --reset
```

That single command: starts the Sonnet proxy, installs the ATLAS hooks into `run/work`,
then runs 20 iterations. Each iteration launches one Haiku session on one OfficeQA question
(oracle mode — the source Treasury-Bulletin doc is copied into the agent's working dir). The
hooks inject the standing prompt, gate the OBSERVE→MAP→CORRELATE→DECIDE reflection, capture
one trace per session, and fire learning automatically.

Useful flags:

| Flag | Meaning |
|------|---------|
| `--n 20` | number of iterations (default 20) |
| `--reset` | wipe `run/` for a fresh program + empty store first |
| `--start 5` | begin at row 5 of the question set |
| `--wait-learning` | after each iteration, **block** until any generation/refinement worker finishes (slow, but you watch the taxonomy appear and get used) |
| `--dashboard` | start one verified fixed-port localhost dashboard owned by the runner |
| `--agent-model` / `--taxonomy-model` | override Haiku / Sonnet ids |
| `--no-proxy --proxy-port 8742` | reuse a proxy you started yourself |

## What to expect

- **Cadence is the framework default** (not exposed through the hook config): generation
  triggers at **5 captured traces**, refinement at **10**, then every **20**. So a 20-iter
  run yields roughly **1 generation + 1 refinement** — the full loop, once each. (To get
  more learning rounds you'd lower the thresholds in `atlas_runtime`, which this runner
  deliberately does not touch.)
- **Generation is slow.** The vendored inducer makes ~8–12 Sonnet calls; over the CLI login
  that is several minutes. By default it runs as a **detached worker** and the new taxonomy
  appears a few minutes after trace 5; pass `--wait-learning` to block after every task.
  Even without that flag, the runner waits for any final in-flight learning job before it
  shuts down the proxy.
- Each iteration prints an `ATLAS: {...}` line — watch `taxonomy_id` flip from `mast` to a
  `tax-…` id, `stored_taxonomies` grow, `refine_rounds` increment, and `fired_codes`
  accumulate.

## Where the results are

```
officeqa/run/
├── program/                      # the ATLAS "program" (trace_output)
│   ├── .atlas-program.json       # manifest: bound taxonomy_id, generation/refinement state
│   ├── pending/                  # captured traces awaiting a learning trigger
│   └── .atlas-runtime-evidence.json   # per-code firing counts + reflection evidence
├── taxonomies/                   # generated/refined taxonomy records (tax-*.json)
├── traces/<taxonomy_id>/         # traces integrated under the active taxonomy
├── work/.claude/                 # installed hooks (settings.local.json) + config
├── results.jsonl                 # one line per iteration (uid, correct?, ATLAS snapshot)
└── cc_proxy.log                  # Sonnet proxy log
```

Inspect the generated taxonomy: `cat run/taxonomies/tax-*.json`. View it live (if you ran
with `--dashboard`, or any time after):

```sh
python -m atlas_runtime.dashboard --trace-output officeqa/run/program --store-dir officeqa/run/taxonomies
```

(run that from the `atlas_skill` directory).

## Notes / honesty

- The OfficeQA **score** printed per iteration (`correct=`) is for your benefit only; it
  **never** enters ATLAS — the learning loop is outcome-blind by construction. Score is
  derived from the task agent's `<FINAL_ANSWER>` inside its captured Claude transcript,
  not from the later Stop-hook reflection returned by headless Claude.
- Each task runs with only its own staged source documents; documents from the previous
  iteration are removed before the next task starts.
- `--reset` clears the program, taxonomy store, and the run-local learning trace root.
- Headless `claude -p` with blocking reflection gates works, but Haiku is a weak model: some
  reflections won't be perfectly shaped, in which case the Stop retry-guard releases the
  boundary after the cap and the trace is still captured. That's expected, not a failure.
- Task answers remain provisional until the Stop gate releases. A reflection whose
  `Decide` says `change:` must use `REPAIR_REQUIRED`; it cannot claim
  `READY_TO_SUBMIT`. The retry prompt explicitly tells the agent to repair and verify
  before emitting a corrected final answer.
- Files in this folder (`cc_proxy.py`, `run_officeqa_atlas.py`) are an orchestrator that
  lives beside the framework; they import `atlas_skill` but do not modify it.
