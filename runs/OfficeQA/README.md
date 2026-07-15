# OfficeQA Pro — ATLAS agent evaluation

Agent evaluation on **OfficeQA Pro** (133 hard questions; Databricks,
[arXiv:2603.08655](https://arxiv.org/pdf/2603.08655)): Claude Code on AWS
Bedrock Claude Haiku 4.5, oracle-parsed condition (each question's oracle
page(s) provided as parsed text), scored with the official `reward.py` from
[databricks/officeqa](https://github.com/databricks/officeqa).

Same model, same harness, same 133 questions in both arms — the only
difference is the ATLAS layer.

## Results

| System | Accuracy (official scorer, exact match) |
|---|---|
| Baseline (no ATLAS) | 44.4% (59/133) |
| **ATLAS** | **51.9% (69/133)** |

Net **+10 questions**. The lift comes from the ATLAS reflection/repair gate
before submission.

## Files

| File | What it is |
|---|---|
| `officeqa_taxonomy.json` | The 15-code failure-mode taxonomy used in the ATLAS run. |

Per-question predictions, scorer rows, prompts, and run manifests are not
included. The table above is a reported summary and cannot be recomputed from
the files in this directory alone.

## The taxonomy

Generated from the baseline run's own transcripts (outcome-blind) with ATLAS
taxonomy generation, then hand-curated to the 15 codes in
`officeqa_taxonomy.json`. It was frozen during the ATLAS run (no in-run
refinement), so both arms are a clean A/B.

## Replicating the experiment

1. **Dataset & scorer**: the OfficeQA Pro 133-question set and official
   `reward.py` from [databricks/officeqa](https://github.com/databricks/officeqa);
   give the agent each question's oracle page(s) from the parsed corpus.
2. **Agent**: Claude Code headless on Bedrock (`CLAUDE_CODE_USE_BEDROCK=1`,
   Claude Haiku 4.5), one isolated working directory per question, tools
   Read/Grep/Glob/Bash, system prompt from the paper's Appendix E.5, answers
   in `<FINAL_ANSWER>` tags.
3. **ATLAS arm**: install the ATLAS skill
   (`pip install "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"`),
   register the included taxonomy
   (`atlas-register-taxonomy --file officeqa_taxonomy.json --id <id>`), and
   install the Claude Code hooks with that taxonomy inherited
   (`atlas-claude-install`), learning frozen (`"freeze": true`).
4. **Baseline arm**: identical, without the ATLAS hooks.
5. Score both runs with the official reward and compare accuracy.
