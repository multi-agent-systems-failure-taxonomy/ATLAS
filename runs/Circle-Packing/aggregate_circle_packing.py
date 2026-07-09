#!/usr/bin/env python3
"""Aggregate circle-packing results (baselines + the taxonomy lineage) into
results/circle_packing_summary.md and results/circle_packing_data.csv.

Metric of interest: after how many scored evaluations (`run_eval` rounds) the
agent first reached combined_score >= 0.997, plus the peak score and cost.

- Baselines: the individual no-taxonomy runs, reported separately.
- Taxonomy: the resume segments (tax-s2 -> tax-s4 -> tax-s5 -> tax-s7) are ONE
  logical run. Resumes were an operator-side artifact (we stopped/relaunched
  and swapped taxonomy versions); each segment was seeded from the previous
  segment's best program, so the eval sequences concatenate into a single
  trajectory from the naive 0.3642 seed. tax-s6 is a superseded dead-end
  branch off tax-s5 (peaked 0.999732 < tax-s7's 0.999735) and is excluded.

Cost: recomputed from saved transcripts with uniform Bedrock Haiku 4.5 list
pricing (in $1 / out $5 / cache-write $1.25 / cache-read $0.10 per MTok) so it
is reproducible. Claude Code's own reported cost is shown in parentheses; for
the June baselines it returned $0 (Bedrock cost not surfaced), so their cost
is the value recorded in the run notes at the time.
"""
from __future__ import annotations
import csv, glob, json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THRESHOLD = 0.997
PRICE = dict(inp=1.0, out=5.0, cw=1.25, cr=0.10)  # $/MTok, Haiku 4.5 Bedrock list

BASELINES = [
    ("base-haiku-noatlas",  0.90),   # (run-note cost; CC logged $0 on Bedrock)
    ("base-haiku-noatlas2", None),   # crashed stub
    ("base-haiku-noatlas3", 1.23),   # run-note cost
    ("base-s1",             None),
]
TAX_LINEAGE = ["tax-s2", "tax-s4", "tax-s5", "tax-s7"]


def eval_scores(run: str) -> list[float]:
    out = []
    p = os.path.join(ROOT, "runs", run, "progress.log")
    if not os.path.exists(p):
        return out
    for line in open(p, encoding="utf-8", errors="replace"):
        m = re.search(r"\[AGENT EVAL\].*combined_score=([0-9.]+)", line)
        if m:
            out.append(float(m.group(1)))
    return out


def token_cost(run: str) -> float | None:
    inp = out_t = cw = cr = 0
    seen = set()
    paths = (glob.glob(os.path.join(ROOT, "runs", run, "transcript*.jsonl"))
             + glob.glob(os.path.join(ROOT, "runs", run, "atlas-evidence", "transcript*.jsonl")))
    for p in paths:
        if os.path.basename(p) in seen:
            continue
        seen.add(os.path.basename(p))
        for line in open(p, encoding="utf-8", errors="replace"):
            if '"usage"' not in line:
                continue
            try:
                u = (json.loads(line).get("message") or {}).get("usage") or {}
            except (json.JSONDecodeError, ValueError):
                continue
            inp += u.get("input_tokens", 0) or 0
            out_t += u.get("output_tokens", 0) or 0
            cw += u.get("cache_creation_input_tokens", 0) or 0
            cr += u.get("cache_read_input_tokens", 0) or 0
    if inp + out_t + cw + cr == 0:
        return None
    return (inp * PRICE["inp"] + out_t * PRICE["out"]
            + cw * PRICE["cw"] + cr * PRICE["cr"]) / 1e6


def cc_cost(run: str) -> float:
    c = 0.0
    p = os.path.join(ROOT, "runs", run, "progress.log")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8", errors="replace"):
            m = re.search(r"cost=\$([0-9.]+)", line)
            if m:
                c = max(c, float(m.group(1)))
    return c


def first_at_threshold(scores: list[float]) -> int | None:
    for i, s in enumerate(scores, 1):
        if s >= THRESHOLD:
            return i
    return None


def main() -> None:
    rows = []

    # --- baselines (each separate) ---
    for run, note_cost in BASELINES:
        sc = eval_scores(run)
        tok = token_cost(run)
        cc = cc_cost(run)
        cost = tok if tok is not None else (note_cost if note_cost is not None else cc)
        rows.append({
            "arm": "baseline", "run": run, "evals": len(sc),
            "peak": round(max(sc), 6) if sc else None,
            "iters_to_0.997": first_at_threshold(sc),
            "cost_usd": round(cost, 2) if cost else cost,
            "cost_source": "token-math" if tok is not None
                           else ("run-note" if note_cost is not None else "cc"),
            "cc_reported": round(cc, 4),
        })

    # --- taxonomy: one logical run, concatenated ---
    concat, seg_lens, tok_sum, cc_sum = [], [], 0.0, 0.0
    for seg in TAX_LINEAGE:
        s = eval_scores(seg)
        concat += s
        seg_lens.append((seg, len(s)))
        t = token_cost(seg)
        tok_sum += t or 0.0
        cc_sum += cc_cost(seg)
    rows.append({
        "arm": "taxonomy", "run": "taxonomy (tax-s2->s4->s5->s7)",
        "evals": len(concat), "peak": round(max(concat), 6),
        "iters_to_0.997": first_at_threshold(concat),
        "cost_usd": round(tok_sum, 2), "cost_source": "token-math",
        "cc_reported": round(cc_sum, 4),
    })

    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)

    # CSV
    csv_path = os.path.join(ROOT, "results", "circle_packing_data.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # Markdown
    def fmt(v):
        return "never" if v is None else str(v)

    md = []
    md.append("# Circle packing (n=26) — results\n")
    md.append("Task: maximize the sum of 26 circle radii in a unit square. "
              "`combined_score = sum_radii / 2.635` (AlphaEvolve's published "
              "value; **1.0 ties it, >1.0 sets a new record**). All runs use "
              "Claude Haiku 4.5 on Bedrock via the Claude Code search "
              "strategy; taxonomy runs add the ATLAS reflection integration.\n")
    md.append(f"**Metric:** scored evaluations (`run_eval` rounds) until "
              f"`combined_score >= {THRESHOLD}` was first reached.\n")

    md.append("## Baselines (no taxonomy)\n")
    md.append("| run | evals | peak score | evals to ≥0.997 | cost (USD) |")
    md.append("|---|---|---|---|---|")
    for r in rows:
        if r["arm"] != "baseline":
            continue
        cost = f"${r['cost_usd']:.2f}" if r["cost_usd"] else "n/a"
        src = "" if r["cost_source"] == "token-math" else f" ({r['cost_source']})"
        md.append(f"| {r['run']} | {r['evals']} | {r['peak']} | "
                  f"{fmt(r['iters_to_0.997'])} | {cost}{src} |")
    md.append("\n*No baseline reached 0.997. Best baseline result: 0.9006 "
              "(base-s1). base-haiku-noatlas2 crashed after 3 evals.*\n")

    tax = next(r for r in rows if r["arm"] == "taxonomy")
    md.append("## Taxonomy (ATLAS integration) — single logical run\n")
    md.append("Resume segments concatenated (each seeded from the previous "
              "segment's best): "
              + " → ".join(f"{s}({n})" for s, n in seg_lens)
              + f" = {tax['evals']} evals total.\n")
    md.append("| metric | value |")
    md.append("|---|---|")
    md.append(f"| evals to first ≥0.997 | **{tax['iters_to_0.997']}** |")
    md.append(f"| peak score | **{tax['peak']}** (sum_radii 2.63430, "
              "vs AlphaEvolve 2.63586) |")
    md.append(f"| total evals | {tax['evals']} |")
    md.append(f"| cost (token-math, uniform pricing) | ${tax['cost_usd']:.2f} |")
    md.append(f"| cost (Claude Code reported) | ${tax['cc_reported']:.2f} |")

    md.append("\n## Headline\n")
    md.append("| approach | reached 0.997? | evals to 0.997 | peak |")
    md.append("|---|---|---|---|")
    md.append("| baseline (best of 4 runs) | no | — | 0.9006 |")
    md.append(f"| taxonomy | yes | {tax['iters_to_0.997']} | {tax['peak']} |")

    md.append("\n---\n*Cost method: token-math = recomputed from saved "
              "transcripts at Haiku 4.5 Bedrock list pricing "
              "($1/$5/$1.25/$0.10 per MTok in/out/cache-write/cache-read); "
              "reproducible. Claude Code's reported cost omits cache-write "
              "premiums and returned $0 for the June baselines (Bedrock), so "
              "those use the cost recorded in the run notes. Regenerate: "
              "`python results/aggregate_circle_packing.py`.*\n")

    md_path = os.path.join(ROOT, "results", "circle_packing_summary.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print("wrote", os.path.relpath(md_path, ROOT))
    print("wrote", os.path.relpath(csv_path, ROOT))
    print("\n=== summary ===")
    for r in rows:
        print(f"  [{r['arm']:8}] {r['run']:32} evals={r['evals']:3} "
              f"peak={r['peak']} 0.997@{fmt(r['iters_to_0.997'])} "
              f"${r['cost_usd']}")


if __name__ == "__main__":
    main()
