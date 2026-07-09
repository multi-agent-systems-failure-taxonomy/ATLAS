# Circle packing (n=26) — ATLAS search evaluation

Task: place 26 non-overlapping circles in the unit square maximizing the sum
of radii. `combined_score = sum_radii / 2.635`, where 2.635 is AlphaEvolve's
published value for this instance — **1.0 ties it, >1.0 sets a new record**.

Both arms run an iterative Claude Code-driven search on **AWS Bedrock Claude
Haiku 4.5**: the agent evolves a packing-construction program, each candidate
is scored by an evaluator (`run_eval`), and the best solution seeds further
iterations. The taxonomy arm adds the **ATLAS reflection integration** (Claude
Code hooks: checkpoints, final gate, trace capture) with the 8-code taxonomy
in `circle_packing_taxonomy.json`; the baseline arm is the same loop without
ATLAS.

**Metric:** scored evaluations until `combined_score >= 0.997` was first
reached.

## Baselines (no taxonomy)

| run | evals | peak score | evals to ≥0.997 | cost (USD) |
|---|---|---|---|---|
| base-haiku-noatlas | 29 | 0.7608 | never | $0.90 (run-note) |
| base-haiku-noatlas2 | 3 | 0.4308 | never | $0.08 (cc) |
| base-haiku-noatlas3 | 25 | 0.7667 | never | $1.23 (run-note) |
| base-s1 | 61 | 0.9006 | never | $2.15 |

No baseline reached 0.997. Best baseline result: 0.9006 (base-s1).
base-haiku-noatlas2 crashed after 3 evals.

## Taxonomy (ATLAS integration) — single logical run

Resume segments concatenated, each seeded from the previous segment's best
solution; together they are one search trajectory from the naive 0.3642 seed.

| metric | value |
|---|---|
| evals to first ≥0.997 | **20** |
| peak score | **0.999735** (sum_radii 2.63430, vs AlphaEvolve 2.63586) |
| total evals | 59 |
| cost (token-math, uniform pricing) | $32.47 |
| cost (Claude Code reported) | $12.79 |

## Headline

| approach | reached 0.997? | evals to 0.997 | peak |
|---|---|---|---|
| baseline (best of 4 runs) | no | — | 0.9006 |
| taxonomy | yes | 20 | 0.999735 |

## Files

| File | What it is |
|---|---|
| `circle_packing_taxonomy.json` | The 8-code failure-mode taxonomy active in the winning search segment (domain: circle packing, n=26). |
| `circle_packing_data.csv` | Raw per-run metrics: arm, run, evals, peak, evals-to-0.997, cost and cost source. |
| `aggregate_circle_packing.py` | Generator for the tables above. Reads the raw run directories (transcripts + evidence; not included here) and recomputes token-math costs. |

## Replicating the experiment

1. **Evaluator**: a `run_eval` harness that takes a candidate
   packing-construction program, verifies the 26 circles are valid
   (non-overlapping, inside the unit square), and returns
   `combined_score = sum_radii / 2.635`.
2. **Search loop**: Claude Code headless on Bedrock
   (`CLAUDE_CODE_USE_BEDROCK=1`, Haiku 4.5), iterating propose → evaluate →
   keep-best, with the running best solution and recent attempt history in
   the agent's working memory. Long searches resume as segments seeded from
   the previous segment's best solution.
3. **Taxonomy arm**: install the ATLAS skill
   (`pip install "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git@ATLAS_SKILL"`),
   register the included taxonomy
   (`atlas-register-taxonomy --file circle_packing_taxonomy.json --id <id>`),
   and install the Claude Code hooks with that taxonomy inherited
   (`atlas-claude-install`), so the agent reflects against the failure modes
   at checkpoints and before each submission.
4. **Baseline arm**: identical, without the ATLAS hooks.
5. Count scored evaluations until `combined_score >= 0.997`.

*Cost method: token-math = recomputed from saved transcripts at Haiku 4.5
Bedrock list pricing ($1/$5/$1.25/$0.10 per MTok in/out/cache-write/cache-read);
reproducible. Claude Code's reported cost omits cache-write premiums and
returned $0 for some Bedrock baselines, which use the cost recorded in run
notes instead.*
