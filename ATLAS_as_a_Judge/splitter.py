"""Deterministic pre-split of a raw trajectory into numbered units.

Primary path: if the trajectory is a JSON object with a ``steps`` list (the
shape produced by the hover/GEPA task programs), each step becomes a unit and a
leading unit 0 carries the top-level context (claim, program, example, ...).

Fallback: a trajectory that is not JSON-with-steps is split by line. Either way
the result is a faithful, index-addressable list of units — no LLM involved.
"""

from __future__ import annotations

import json
import re

from .models import Unit

# Step markers emitted by the benchmark trace formatters, e.g. "--- Agent Step 3 ---".
_STEP_MARKER = re.compile(r"(?m)^-{2,3}\s*Agent Step\b.*$")


def split_units(raw_trajectory: str) -> list[Unit]:
    units = _split_json_steps(raw_trajectory)
    if units is not None:
        return units
    units = _split_step_markers(raw_trajectory)
    if units is not None:
        return units
    return _split_lines(raw_trajectory)


def _split_json_steps(raw: str) -> list[Unit] | None:
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    steps = obj.get("steps")
    if not isinstance(steps, list) or not steps:
        return None

    units: list[Unit] = []
    context = {k: v for k, v in obj.items() if k != "steps"}
    units.append(Unit(0, json.dumps(context, ensure_ascii=False), "context"))
    for i, step in enumerate(steps, start=1):
        name = step.get("name", "step") if isinstance(step, dict) else "step"
        units.append(Unit(i, json.dumps(step, ensure_ascii=False), f"step:{name}"))
    return units


def _split_step_markers(raw: str) -> list[Unit] | None:
    """Split a step-formatted trace (``--- Agent Step N ---`` blocks) into units.

    Each step block becomes a unit; any preamble before the first marker is
    unit 0. Trailing sections (e.g. a final ``--- Final Code Patch ---``) fold
    into the last step's unit. Returns None if there are not >= 2 step markers.
    """
    if not raw:
        return None
    positions = [m.start() for m in _STEP_MARKER.finditer(raw)]
    if len(positions) < 2:
        return None
    units: list[Unit] = []
    if positions[0] > 0:
        pre = raw[: positions[0]].strip()
        if pre:
            units.append(Unit(len(units), pre, "preamble"))
    bounds = positions + [len(raw)]
    for i in range(len(positions)):
        seg = raw[bounds[i] : bounds[i + 1]].strip()
        if not seg:
            continue
        first = seg.splitlines()[0].strip()
        units.append(Unit(len(units), seg, (first or "step")[:40]))
    return units


def _split_lines(raw: str, *, min_chars: int = 1) -> list[Unit]:
    """Fallback: one unit per non-blank line (kept simple; used only for
    trajectories that are not JSON-with-steps)."""
    lines = [ln for ln in (raw or "").splitlines() if ln.strip()]
    if not lines:
        return [Unit(0, raw or "", "whole")]
    return [Unit(i, ln, "line") for i, ln in enumerate(lines)]
