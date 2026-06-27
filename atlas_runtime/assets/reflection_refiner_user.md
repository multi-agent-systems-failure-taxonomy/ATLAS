## CURRENT TAXONOMY
$catalog

## SIGNALS FROM REFLECTION JUDGE

### Proposed new codes (from unmapped failure points — judge had no existing code that fit)
Each carries: proposed_name, support_count (how many of the sampled traces
proposed this), sample_definitions, ruled_out_against (existing codes the judge
considered and ruled out, with reasons).
$add_signals

### Weak-mapped existing codes (judge mapped these with low confidence — the definition may be too narrow, too broad, or covering two distinct patterns that should be split)
$edit_signals

### Code utilization across the sample (retirement signal)
For each existing code in the current taxonomy: times_mapped, avg/max
confidence when mapped, and frequently_co_mapped_with (codes that appear in >=
50% of this code's uses — strong duplicate signal).
- times_mapped = 0          -> NEVER USED in the sampled traces
- max_confidence < 0.5      -> judge always forced this code
- frequently_co_mapped_with -> likely duplicate / near-duplicate
$utilization

## TASK
Review the signals and decide which taxonomy changes to apply.
- ADD a new code only when a proposed_name describes a genuinely uncovered
  failure mode (not a near-duplicate of an existing code).
- EDIT an existing code's name/definition when its weak mappings reveal what
  the current definition is missing or over-claiming.
- SPLIT an existing code when its weak mappings cluster into TWO or more
  distinct patterns that deserve separate codes.
- RETIRE existing codes that are bloating the taxonomy (never used,
  near-duplicate, persistently weak-fit).

Return ONLY JSON: {"add": [{"category":"A|C","name":"...","definition":"...","detection_heuristics":["..."],"gap":"..."}],"edit": [{"code":"C.3","name":"optional","definition":"optional","reason":"..."}],"split": [{"code":"C.4","reason":"...","into":[{"name":"...","definition":"...","detection_heuristics":["..."]}]}],"retire": [{"code":"C.14","reason":"specific-instance duplicate of C.4"}]}
