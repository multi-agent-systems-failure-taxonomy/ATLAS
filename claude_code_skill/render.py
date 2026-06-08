"""Skill body render step.

Two sources, one output:

  source = MAST floor (mast_floor.md, already-prose body)
      ->  read verbatim, append the checkpoint protocol, write SKILL.md

  source = induced taxonomy (a taxonomy.json from atlas.generate_taxonomy)
      ->  build frontmatter, render annotation_layer to prose, append the
          checkpoint protocol, write SKILL.md

The render step is invoked:
  - once at install time (with MAST as the source) to seed SKILL.md
  - once at T1 induction when the live taxonomy swaps MAST -> induced
  - once at every refinement (ΔN traces past T1) to refresh the body

It never persists the taxonomy to disk by itself — it only rewrites the
SKILL.md file that Claude Code reads. Trace state lives in the in-memory
accumulator; this module is the rendering edge of that state.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Union

SKILL_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = SKILL_DIR / "templates"
MAST_FLOOR_PATH = SKILL_DIR / "mast_floor.md"
PROTOCOL_PATH = TEMPLATES_DIR / "protocol.md"

INDUCED_FRONTMATTER = """\
---
name: atlas-failure-modes
description: Consult this induced failure-mode taxonomy whenever you are about to act on a multi-step task — debugging, code editing, patch submission, multi-tool workflows. Apply the checkpoint protocol at the listed segment boundaries and run the final-gate before declaring the task complete.
---

# ATLAS failure-mode taxonomy
"""


@dataclass
class RenderResult:
    body: str
    source_kind: str  # "mast" | "induced"
    char_count: int


def _load_protocol(max_retries: int) -> str:
    return PROTOCOL_PATH.read_text(encoding="utf-8").format(max_retries=max_retries)


def render_priors_body(taxonomy: dict) -> str:
    """Render an induced taxonomy's annotation_layer into prose.

    No pre-selection. Every A/B/C code lands in the output, with stable IDs.
    Ported from claude-code-experiment/scripts/exp2/build_skills.py.
    """
    lines = ["", ""]
    md_meta = taxonomy.get("metadata", {})
    counts = md_meta.get("counts", {})
    lines.append(
        f"_Induced from {md_meta.get('traces_analyzed', '?')} traces. "
        f"{counts.get('category_a', 0)} A / {counts.get('category_b', 0)} B / "
        f"{counts.get('category_c', 0)} C codes._"
    )
    lines.append("")

    annot = taxonomy.get("annotation_layer", {})
    cat_defs = taxonomy.get("category_definitions", {})

    for axis, label in [
        ("category_a", "A — System-level failures (agent-independent)"),
        ("category_b", "B — Role-specific quality failures"),
        ("category_c", "C — Domain reasoning failures"),
    ]:
        codes = annot.get(axis, [])
        if not codes:
            continue
        lines.append(f"## {label}")
        cat_letter = axis[-1].upper()
        if cat_defs.get(cat_letter):
            lines.append(f"_{cat_defs[cat_letter]}_")
        lines.append("")
        for c in codes:
            cid = c.get("code") or c.get("id") or "?"
            name = c.get("name", "")
            sev = c.get("severity", "")
            defn = c.get("definition") or c.get("description", "")
            tag = f"{name}, {sev}" if name and sev else (name or sev)
            head = f"- **{cid}** ({tag}). " if tag else f"- **{cid}**. "
            lines.append(f"{head}{defn}")
        lines.append("")

    return "\n".join(lines)


def render(
    source: Union[Path, dict, str],
    *,
    max_retries: int = 3,
) -> RenderResult:
    """Render a SKILL.md body from either MAST or an induced taxonomy.

    source:
      Path to mast_floor.md (or "mast" string)         -> MAST mode (verbatim copy)
      Path to a taxonomy.json file                     -> induced mode
      dict (already-loaded taxonomy)                   -> induced mode
    """
    protocol = _load_protocol(max_retries=max_retries)

    if isinstance(source, str) and source.lower() == "mast":
        source = MAST_FLOOR_PATH

    if isinstance(source, Path) and source.suffix.lower() == ".md":
        body = source.read_text(encoding="utf-8").rstrip() + "\n\n" + protocol
        return RenderResult(body=body, source_kind="mast", char_count=len(body))

    if isinstance(source, Path):
        taxonomy = json.loads(source.read_text(encoding="utf-8"))
    else:
        taxonomy = source

    body = (
        INDUCED_FRONTMATTER.rstrip()
        + "\n"
        + render_priors_body(taxonomy).rstrip()
        + "\n\n"
        + protocol
    )
    return RenderResult(body=body, source_kind="induced", char_count=len(body))


def write_skill_md(result: RenderResult, target: Path) -> None:
    target.write_text(result.body, encoding="utf-8")


def render_to_file(
    source: Union[Path, dict, str],
    target: Path,
    *,
    max_retries: int = 3,
) -> RenderResult:
    """One-shot: render and write SKILL.md in place. Used by install + at every
    taxonomy swap (T1, refinement)."""
    result = render(source, max_retries=max_retries)
    write_skill_md(result, target)
    return result


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Render SKILL.md from MAST or an induced taxonomy.")
    ap.add_argument("--source", default="mast",
                    help="'mast' (default), path to a .md body, or path to a taxonomy.json")
    ap.add_argument("--target", default=str(SKILL_DIR / "SKILL.md"),
                    help="Output path for SKILL.md")
    ap.add_argument("--max-retries", type=int, default=3,
                    help="Final-gate repair retry cap baked into the protocol body")
    args = ap.parse_args()

    src: Union[str, Path] = args.source
    if args.source != "mast":
        src = Path(args.source)

    result = render_to_file(src, Path(args.target), max_retries=args.max_retries)
    print(f"wrote {args.target}  source={result.source_kind}  chars={result.char_count}")
