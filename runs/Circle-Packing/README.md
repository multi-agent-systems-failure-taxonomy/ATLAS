# Circle packing (n=26) — ATLAS search evaluation

Task: place 26 non-overlapping circles in the unit square maximizing the sum
of radii. `combined_score = sum_radii / 2.635`, where 2.635 is AlphaEvolve's
published value for this instance — 1.0 ties it.

The search harness is
[SkyDiscover](https://github.com/skydiscover-ai/skydiscover)'s Claude Code
search strategy: the agent iteratively evolves a packing-construction program
and each candidate is scored by the task evaluator. All runs use Claude Haiku
4.5 on AWS Bedrock. The ATLAS arm adds the ATLAS reflection integration
(Claude Code hooks: checkpoints and the pre-submission gate) with the taxonomy
in `circle_packing_taxonomy.json`; the baseline arm is the same SkyDiscover
loop without ATLAS.

## Results

Metric: scored evaluations until `combined_score >= 0.997` is first reached.

| run | evals | peak score | evals to ≥0.997 |
|---|---|---|---|
| baseline 1 | 29 | 0.7608 | never |
| baseline 2 | 25 | 0.7667 | never |
| baseline 3 | 61 | 0.9006 | never |
| **ATLAS** | 59 | **0.999735** | **20** |

No baseline reached 0.997. The ATLAS run reached it in 20 evaluations and
peaked at 0.999735 (sum_radii 2.63430 vs AlphaEvolve's 2.63586). The ATLAS
run's resume segments form one continuous search trajectory, each segment
seeded from the previous segment's best solution.

## Files

| File | What it is |
|---|---|
| `circle_packing_taxonomy.json` | The 8-code failure-mode taxonomy used by the ATLAS run. |

## Replicating the experiment

1. Run [SkyDiscover](https://github.com/skydiscover-ai/skydiscover)'s Claude
   Code search strategy on the circle-packing (n=26) task, with Claude Code
   on Bedrock (`CLAUDE_CODE_USE_BEDROCK=1`, Claude Haiku 4.5).
2. **ATLAS arm**: install the ATLAS skill
   (`pip install "git+https://github.com/multi-agent-systems-failure-taxonomy/ATLAS.git"`),
   register the included taxonomy
   (`atlas-register-taxonomy --file circle_packing_taxonomy.json --id <id>`),
   and install the Claude Code hooks with that taxonomy inherited
   (`atlas-claude-install`).
3. **Baseline arm**: identical, without the ATLAS hooks.
4. Count scored evaluations until `combined_score >= 0.997`.
