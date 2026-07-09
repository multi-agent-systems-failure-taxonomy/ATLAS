# OfficeQA Pro — ATLAS agent evaluation

Agentic-harness evaluation on **OfficeQA Pro** (133 hard questions; Databricks,
[arXiv:2603.08655](https://arxiv.org/pdf/2603.08655)), Claude Code on **AWS
Bedrock Claude Haiku 4.5** (`us.anthropic.claude-haiku-4-5-20251001-v1:0`),
oracle-parsed condition: each question's oracle page(s) provided as parsed text
with HTML tables; web search off. Scoring is the official `reward.py` from
[databricks/officeqa](https://github.com/databricks/officeqa) — exact match
with an allowable absolute relative error threshold.

Two systems, **same model, same harness, same 133 questions** — the only
difference is the ATLAS layer.

## Results (strict, official metric = 0% allowable absolute relative error)

| System | @0% | @0.1% | @1% | @5% |
|---|---|---|---|---|
| Baseline (no ATLAS) | 44.4% (59/133) | 46.6% | 54.1% | 63.2% |
| ATLAS (taxonomy + reflection gate) | **51.9% (69/133)** | 53.4% | 60.2% | 63.9% |

Matched pairs: ATLAS-only wins **20**, baseline-only wins **10**, both correct
49, both wrong 54. Net **+7.5 pts / +10 questions**. McNemar p ≈ 0.10.

The ATLAS lift comes from the reflection/repair gate (pre-gate accuracy ≈
baseline); the taxonomy-in-context channel contributed ~0 in agent mode.

## Files

| File | What it is |
|---|---|
| `agent_oracle_baseline.jsonl` | Baseline run, 133 rows, no ATLAS. |
| `agent_oracle_atlas.jsonl` | ATLAS run, 133 rows — the headline number above. |
| `officeqa_taxonomy.json` | The 15-code failure-mode taxonomy used in the ATLAS run (domain: U.S. government financial document QA). |

## Row format (one JSON object per line, both run files identical schema)

```json
{
  "uid": "UID0001",
  "config": "oracle",
  "mode": "baseline | atlas",
  "model": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
  "question": "<full question text>",
  "gold": "<ground-truth answer string>",
  "predicted": "<extracted final answer>",
  "scores":         {"0%": 0.0, "0.1%": 0.0, "1%": 0.0, "5%": 0.0},
  "scores_lenient": {"0%": 0.0, "0.1%": 0.0, "1%": 0.0, "5%": 0.0},
  "num_turns": 14,
  "usage": { "...": "Claude Code token usage object" },
  "total_cost_usd": 0.0250,
  "elapsed_s": 28.7,
  "result_text": "<full final assistant message; reward extracts the last <FINAL_ANSWER> tag>"
}
```

`scores` = official reward. `scores_lenient` = same scorer after stripping
currency words/units the question already specified (reported alongside, not
the headline).

## How the taxonomy was built

Generated from the baseline run's own transcripts (an outcome-blind
50-transcript subset) with ATLAS taxonomy generation (Claude Opus generation +
Reflection Judge), then hand-curated and evidence-bounded to the 15 codes in
`officeqa_taxonomy.json`. It was **frozen** during the ATLAS run (no in-run
refinement), so both arms are a clean A/B.

## Replicating the experiment

1. **Dataset & scorer**: OfficeQA Pro 133-question set and the official
   `reward.py` from [databricks/officeqa](https://github.com/databricks/officeqa).
   Oracle-parsed condition: give the agent each question's oracle page(s) from
   the parsed corpus (697 bulletins as text with HTML tables).
2. **Agent harness**: Claude Code headless on Bedrock
   (`CLAUDE_CODE_USE_BEDROCK=1`, model id above), one isolated working
   directory per question, tools limited to Read/Grep/Glob/Bash, system prompt
   transcribed from the paper's Appendix E.5, output contract
   `<REASONING>…</REASONING>` + `<FINAL_ANSWER>value</FINAL_ANSWER>`.
3. **ATLAS arm**: install the ATLAS skill
   (`pip install "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"`),
   register the included taxonomy
   (`atlas-register-taxonomy --file officeqa_taxonomy.json --id <id>`), and
   install the Claude Code hooks per question with that taxonomy inherited
   (`atlas-claude-install`), learning frozen (`"freeze": true`) and 2
   final-gate repair rounds. ATLAS's own learning/judge calls also run on
   Bedrock Haiku.
4. **Baseline arm**: identical, without the ATLAS hooks.
5. Score each run file with the official reward at 0% / 0.1% / 1% / 5%
   thresholds and compare matched pairs per `uid`.

Costs for reference: baseline $12.07, ATLAS run $31.80 (Bedrock list pricing).
