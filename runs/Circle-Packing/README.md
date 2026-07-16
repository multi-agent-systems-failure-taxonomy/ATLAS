# Circle packing (n=26) — AdaMAST search evaluation

Task: place 26 non-overlapping circles in the unit square maximizing the sum
of radii. `combined_score = sum_radii / 2.635`, where 2.635 is AlphaEvolve's
published value for this instance — 1.0 ties it.

The search harness is
[SkyDiscover](https://github.com/skydiscover-ai/skydiscover)'s Claude Code
search strategy: the agent iteratively evolves a packing-construction program
and each candidate is scored by the task evaluator. All runs use Claude Haiku
4.5 on AWS Bedrock. The AdaMAST arm adds the AdaMAST reflection integration
(Claude Code hooks: checkpoints and the pre-submission gate) with the taxonomy
in `circle_packing_taxonomy.json`; the baseline arm is the same SkyDiscover
loop without AdaMAST.

## Results

Metric: scored evaluations until `combined_score >= 0.997` is first reached.

| run | evals | peak score | evals to ≥0.997 |
|---|---|---|---|
| baseline 1 | 29 | 0.7608 | never |
| baseline 2 | 25 | 0.7667 | never |
| baseline 3 | 61 | 0.9006 | never |
| **AdaMAST** | 59 | **0.999735** | **20** |

No baseline reached 0.997. The AdaMAST run reached it in 20 evaluations and
peaked at 0.999735 (sum_radii 2.63430 vs AlphaEvolve's 2.63586). The AdaMAST
run's resume segments form one continuous search trajectory, each segment
seeded from the previous segment's best solution.

## Files

| File | What it is |
|---|---|
| `circle_packing_taxonomy.json` | The 8-code failure-mode taxonomy used by the AdaMAST run. |

Per-evaluation candidates, scores, prompts, seeds, and run manifests are not
included. The table above is a reported summary and cannot be recomputed from
the files in this directory alone.

## Replicating the experiment

1. Run [SkyDiscover](https://github.com/skydiscover-ai/skydiscover)'s Claude
   Code search strategy on the circle-packing (n=26) task, with Claude Code
   on Bedrock (`CLAUDE_CODE_USE_BEDROCK=1`, Claude Haiku 4.5).
2. **AdaMAST arm**: install the AdaMAST skill
   (`pip install adamast`),
   register the included taxonomy
   (`adamast-register-taxonomy --file circle_packing_taxonomy.json --id <id>`),
   and install the Claude Code hooks with that taxonomy inherited
   (`adamast-claude-install`).
3. **Baseline arm**: identical, without the AdaMAST hooks.
4. Count scored evaluations until `combined_score >= 0.997`.
