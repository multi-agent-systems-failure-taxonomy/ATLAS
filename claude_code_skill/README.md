# 🧭 ATLAS Skill for Claude Code

<div align="center">

**Pattern-A failure-mode taxonomy as a Claude Code skill — the agent self-applies the taxonomy, the Stop hook structurally enforces it.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-2.0+-8B5CF6.svg)](https://claude.com/code)
[![Built on ATLAS](https://img.shields.io/badge/built%20on-ATLAS-2EA44F.svg)](https://github.com/multi-agent-systems-failure-taxonomy/ATLAS)
[![Tests](https://img.shields.io/badge/tests-6%2F6%20passing-success.svg)](#-smoke-tests)
[![Pattern](https://img.shields.io/badge/pattern-A%20(self--applied)-orange.svg)](#-how-the-lifecycle-runs-in-one-conversation)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/multi-agent-systems-failure-taxonomy/ATLAS/pulls)

</div>

---

## 📑 Table of contents

- [🚀 Quick install](#-quick-install)
- [💡 What this is](#-what-this-is)
- [🎯 Scope — single conversation, full lifecycle](#-scope--single-conversation-full-lifecycle)
- [🌱 Seeding at startup (optional)](#-seeding-at-startup-optional)
- [🔄 How the lifecycle runs in one conversation](#-how-the-lifecycle-runs-in-one-conversation)
- [🎛️ Config knobs](#️-config-knobs)
- [🧪 Smoke tests](#-smoke-tests)
- [📂 File map](#-file-map)
- [❓ FAQ](#-faq)
- [📚 Reference](#-reference)
- [📄 License](#-license)

---

## 🚀 Quick install

```bash
pip install git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL
bash "$(python -c 'import claude_code_skill, os; print(os.path.dirname(claude_code_skill.__file__))')/installer/install.sh"
export ANTHROPIC_API_KEY=sk-ant-...     # for inducer / refiner (claude-opus-4-8)
```

That's it. Open Claude Code, start a SWE-style task, and the skill auto-triggers via the frontmatter `description` field. The Stop hook will not let you submit without the 5-field final-gate block.

**Uninstall:**

```bash
bash "$(python -c 'import claude_code_skill, os; print(os.path.dirname(claude_code_skill.__file__))')/installer/uninstall.sh"
```

Both scripts are idempotent.

---

## 💡 What this is

A Claude Code skill that wraps the [ATLAS](https://github.com/multi-agent-systems-failure-taxonomy/ATLAS) failure-mode taxonomy and applies it as **in-prompt priors plus a blocking final-gate hook**.

| | |
|---|---|
| 🅿️ **Pattern** | **A** — no external judge, no second LLM call between the agent and its submission. The agent self-applies the taxonomy under the checkpoint protocol. |
| 🚧 **Enforcement** | The Stop hook is the structural backstop. It reads the transcript, finds the final-gate block, and blocks the submission until the block is present and valid (or until the 3 repair retries are exhausted). |
| 🧬 **Taxonomy lifecycle** | MAST floor → seed-induce or T1-induce → refine every ΔN. Lives entirely **inside one conversation** — nothing persists across conversations. |
| 🧠 **Inducer model** | `claude-opus-4-8` by default. **Independent of the runtime agent's model.** Solver decides what failures appear in traces; inducer decides how cleanly they get categorized. |

---

## 🎯 Scope — single conversation, full lifecycle

The full lifecycle runs **inside one conversation**. Nothing is written across conversations.

<table>
<tr>
<th>✅ In scope</th>
<th>🚫 Out of scope</th>
</tr>
<tr>
<td>

- MAST as the fallback / floor taxonomy
- Optional seed traces at startup (`--seed-traces`)
- In-memory trace accumulation
- Local induction at T1 with a quality floor
- Refinement every ΔN (refine, not regenerate)
- Stop hook (blocking) + PostToolUse hook
- Skill auto-trigger via frontmatter `description`

</td>
<td>

- Persistence across conversations / durable trace store
- Task classifier / per-type buckets / quarantine
- Inter-annotator agreement / Level-4 validation
- Multi-bucket or per-type thresholds
- Anything that crosses the conversation boundary

</td>
</tr>
</table>

> **Governing rule:** the seed file is **read-once input** at startup; it is not the start of a persistent store.

---

## 🌱 Seeding at startup (optional)

If you have prior traces from any agent system, pre-populate the accumulator and skip the MAST warmup:

```bash
python -m claude_code_skill.seed_adapter --seed-traces path/to/seeds.jsonl
```

The loader auto-detects **7 trace formats** via the upstream `atlas.traces.loader`:

| Format          | Detection key                              |
|-----------------|---------------------------------------------|
| ATLAS unified   | `raw_trajectory` field                      |
| tau-bench       | `traj` + `task_id` + `reward`               |
| Codex CLI       | `type: session_meta/...` per JSONL line     |
| Event log       | `event` field per JSONL entry               |
| Conversation    | `messages` list of role/content dicts       |
| KIRA            | step dicts with `step_id` + `tool_calls`    |
| Plain text      | any string                                  |

After seeding, calling `runtime.attempt_induction()` from your host script promotes to an induced taxonomy if the quality floor passes — or keeps MAST live with a `"low-confidence, using MAST"` reason on the surface.

The seed file is consumed once at startup. It is not appended to or written back.

---

## 🔄 How the lifecycle runs in one conversation

```
startup ─┬─►  if --seed-traces:  load_seeds(); attempt_induction()
         └─►  else:               ensure_floor_rendered()        🟢 MAST live

per task ─►  agent works
         ─►  Stop hook fires:
                ✅ READY_TO_SUBMIT      →  push Trace, runtime.tick()
                🔁 REPAIR_REQUIRED (<max) →  BLOCK, agent repairs and resubmits
                ⚠️  REPAIR_REQUIRED (=max) →  push Trace marked unresolved, allow

runtime.tick() decides:
   count() ≥ T1            →  🚀 attempt_induction(): swap MAST → induced + re-render
   promoted, ΔN passed     →  ✨ attempt_refinement(): refine in place + re-render
   otherwise               →  ⏸  no-op
```

---

## 🎛️ Config knobs

All values are settable via `claude_code_skill/config.toml` **or** environment variables.

<table>
<tr><th>Section</th><th>Key</th><th>Default</th><th>Env var</th></tr>

<tr><td rowspan="5">🚀 induction</td>
<td><code>t1_threshold</code></td><td>5</td><td><code>ATLAS_T1</code></td></tr>
<tr><td><code>min_support_per_code</code></td><td>2</td><td><code>ATLAS_MIN_SUPPORT</code></td></tr>
<tr><td><code>min_total_codes</code></td><td>8 (the <em>K</em>)</td><td><code>ATLAS_MIN_CODES</code></td></tr>
<tr><td><code>max_codes_cap</code></td><td>30</td><td><code>ATLAS_MAX_CODES_CAP</code></td></tr>
<tr><td><code>inducer_model</code></td><td><code>claude-opus-4-8</code></td><td><code>ATLAS_INDUCER_MODEL</code></td></tr>

<tr><td rowspan="3">✨ refinement</td>
<td><code>delta_n</code></td><td>5</td><td><code>ATLAS_DELTA_N</code></td></tr>
<tr><td><code>min_interval</code></td><td>3</td><td><code>ATLAS_MIN_REFINE_INTERVAL</code></td></tr>
<tr><td><code>refiner_model</code></td><td><code>claude-opus-4-8</code></td><td><code>ATLAS_REFINER_MODEL</code></td></tr>

<tr><td>🚦 gate</td>
<td><code>max_retries</code></td><td>3</td><td><code>ATLAS_MAX_FINAL_RETRIES</code></td></tr>

<tr><td rowspan="2">🔔 post_tool_use</td>
<td><code>throttle_every_n_calls</code></td><td>5</td><td><code>ATLAS_POSTTOOL_THROTTLE</code></td></tr>
<tr><td><code>recency_window_turns</code></td><td>3</td><td><code>ATLAS_POSTTOOL_RECENCY</code></td></tr>
</table>

> **Why pin the inducer to a strong model?** Solver model decides *what failures show up in traces*; inducer model decides *how cleanly those failures get categorized*. Tying the two together would penalize taxonomy quality on weak-solver runs for no good reason. So `inducer_model` is pinned independent of the runtime agent.

---

## 🧪 Smoke tests

```bash
python -m pytest tests/ -v
```

Two scenarios are covered, total **6/6 passing**:

| Test file | What it proves |
|-----------|----------------|
| `tests/test_stop_hook.py` | Stop hook denies completion without the final-gate block; denies on `REPAIR_REQUIRED` with attempts remaining; allows on `READY_TO_SUBMIT`; allows-with-unresolved on `REPAIR_REQUIRED` with attempts exhausted. |
| `tests/test_t1_swap.py` | 5 healthy traces with multi-trace support → induction promotes + `SKILL.md` flips from MAST to the induced body. A thin / singleton-support taxonomy → quality floor rejects + `SKILL.md` stays on MAST. |

`atlas.generate_taxonomy` is mocked in the T1 tests so the suite is hermetic (no LLM call, no API key required).

---

## 📂 File map

```
claude_code_skill/
├── SKILL.md                  🟢 rendered skill body (regenerated on every swap)
├── mast_floor.md             📜 Cemri et al. 2025 14-mode MAST, verbatim floor
├── templates/protocol.md     📐 checkpoint + final-gate protocol template
├── render.py                 ✍️  SKILL.md renderer (MAST + induced modes)
├── accumulator.py            📦 in-memory Trace pile (one shared schema)
├── seed_adapter.py           🌱 --seed-traces wrapper over atlas.traces.loader
├── induction.py              🚀 generate_taxonomy + quality floor + MAST fallback
├── refinement.py             ✨ refine-not-regenerate; stable IDs; structured diff
├── runtime.py                🔄 tick(): T1 / ΔN orchestrator
├── config.toml               🎛️ all knobs
├── hooks/
│   ├── stop.py               🚦 blocking final-gate enforcement (evidence-gated)
│   └── post_tool_use.py      🔔 throttled checkpoint reminder on observable failure
└── installer/
    ├── install.sh            📥 copies skill + registers hooks (idempotent)
    └── uninstall.sh          📤 removes skill + unregisters hooks (idempotent)
```

---

## ❓ FAQ

<details>
<summary><b>Do I need any API keys?</b></summary>
<br>

Yes, one. Set `ANTHROPIC_API_KEY` for the inducer / refiner (Claude Opus by default), or `OPENAI_API_KEY` if you point the inducer model at an OpenAI model via `ATLAS_INDUCER_MODEL`. Atlas itself accepts either via env.

</details>

<details>
<summary><b>Will this clobber my other Claude Code skills?</b></summary>
<br>

No. The installer puts the skill in its own subdirectory at `~/.claude/skills/atlas-failure-modes/`. The hooks are added to `~/.claude/settings.json` under `hooks.Stop` and `hooks.PostToolUse`, appended — existing hooks are preserved.

</details>

<details>
<summary><b>What if I don't want to touch my real Claude Code config?</b></summary>
<br>

Override the install destination:

```bash
CLAUDE_SKILLS_DIR=/tmp/test/skills \
CLAUDE_SETTINGS=/tmp/test/settings.json \
bash installer/install.sh
```

Both install and uninstall honor these envs. Used by the smoke tests too.

</details>

<details>
<summary><b>Why MAST as the floor and not just induce from zero?</b></summary>
<br>

Because the first 1-4 task attempts in a conversation can't yield a meaningful induced taxonomy — there's no signal yet. The MAST 14 modes (Cemri et al. 2025) are hand-curated to apply universally across multi-agent LLM systems, so they're a reasonable "in-distribution" prior while you wait for the in-conversation induction at T1 to fire.

</details>

<details>
<summary><b>What's the quality floor for?</b></summary>
<br>

Before promoting from MAST to an induced taxonomy, the floor drops singleton-support codes (`min_support_per_code`, default 2) and requires at least K surviving codes (`min_total_codes`, default 8). If the floor fails, the runtime keeps MAST live and surfaces `"low-confidence, using MAST"`. The asymmetry is in visibility — silent thin-taxonomy ship is the failure mode this prevents.

</details>

<details>
<summary><b>Does this persist anything across conversations?</b></summary>
<br>

**No.** That's an explicit out-of-scope rule. The accumulator is in-memory only; everything resets at process exit. The seed file is the one exception — it's a read-once input, not the start of a persistent store.

</details>

<details>
<summary><b>Pattern A vs Pattern B?</b></summary>
<br>

Pattern A = agent self-applies the taxonomy (this skill).
Pattern B = an external LLM judge classifies the trace after submission. Pattern B is **not** part of this skill and is OUT OF SCOPE for the simple-scenario runtime. The Stop hook is the only non-agent piece, and it's structural — regex-matching on the transcript, no LLM call.

</details>

---

## 📚 Reference

| | |
|---|---|
| 🧪 **Taxonomy induction library** | [ATLAS — Automatic Taxonomy Learning for Agent Systems](https://github.com/multi-agent-systems-failure-taxonomy/ATLAS) (main branch) |
| 📜 **MAST floor** | Cemri et al. (2025), *Why Do Multi-Agent LLM Systems Fail?*, [arXiv:2503.13657](https://arxiv.org/abs/2503.13657) |
| 🔬 **Refinement engine** | Ported and stripped from the evolutionary taxonomy pipeline's stagnation-driven refiner. |

---

## 📄 License

[MIT](LICENSE) — same as the upstream ATLAS library.
